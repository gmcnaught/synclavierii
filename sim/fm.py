"""Original Synclavier II FM synthesizer: register semantics (M3.1a).

Pitch (below), the envelope/index interpolators, ISHC (pan + shift),
modulation, TIM and wave memory (further down); spec in docs/fm-voice.md.

Pitch registers of a channel (D161 function codes 0-2, see
docs/devices/d160-fm-interface.md and docs/fm-voice.md):

    INC (0) = increment - 1
    NNU (1) = 256 - divisor + (INC >> 3)
    ONU (2) = octave number 0-7

Evidence:
  * Patent US 4,345,500 (note oscillator): output frequency = clock x
    Increment / Divisor; Io = Increment - 1/16, Do = (256 - Divisor) +
    (Increment - 1/16); the output is divided by a power of two (octave).
  * NED COMPUTE.OSYN.FREQ (SYNRSOU 11-TIMB:137-COMP; the same routine runs
    in Release L ORK-LM at 015322): NOTEINC = inc - 1, NOTENUM = 256 - div +
    SHR(NOTEINC, 3), NOTEADD = SHR(FREQ, 10) - 1 (max 7), with (inc, div)
    from the .STAB-6 frequency table indexed by FREQ & 1023.
  * NED's log frequency: 1024 steps per octave, 2816 = A 440 Hz.
  * Release L ORK-LM writes, checked: key 36 (middle C) -> 261.64 Hz,
    key 45 -> 440.00 Hz, key 72 -> 2092.68 Hz with K below.
"""

#: Hz per unit of 2^ONU * inc / divisor. From .STAB-6 entry 768 (A 440 at
#: log 2816: ONU 1, inc 123, divisor 91): K = 440 / (2 * 123 / 91).
K_HZ = 440 * 91 / (2 * 123)

#: Points per waveform; each oscillator pulse steps one point.
WAVE_POINTS = 256


def oscillator(onu, nnu, inc):
    """(increment, divisor, octave) from the register values."""
    increment = (inc & 0o377) + 1
    divisor = 256 - (nnu & 0o377) + ((inc & 0o377) >> 3)
    return increment, divisor, onu & 7


def frequency(onu, nnu, inc):
    """Fundamental frequency in Hz of a channel's waveform."""
    increment, divisor, octave = oscillator(onu, nnu, inc)
    return K_HZ * (1 << octave) * increment / divisor


def registers(increment, divisor, octave):
    """Register values (ONU, NNU, INC) for an (increment, divisor, octave)."""
    inc = increment - 1
    return octave, 256 - divisor + (inc >> 3), inc


def log_frequency_hz(freq_num):
    """NED's internal log frequency (1024/octave, 2816 = A 440) in Hz."""
    return 440.0 * 2 ** ((freq_num - 2816) / 1024)


# --- Interpolators: volume envelope (odd channel), index envelope (even) ---
#
# Card analysis (SS3): "an 8 bit prescaler (divide by n counter) followed by
# an 8 bit rate generator (phase accumulator) and 8 bit up/down counter".
# NED 302-SUB2 NEW.SCALE.DIV/ADD and 138-PRE1 COMPUTE.INTERP.NUMBERS give
# the encodings: hardware divisor = 256 - logical divisor (1-256), hardware
# adder = logical adder - 1 (1-256). The counter moves one step toward the
# limit per accumulator carry and stops at the limit ("the envelope
# interpolator runs towards the new limit at the old rate", 144-TIM3).
#
#   counter steps/s = ENV_CLOCK_HZ * (ADD + 1) / (256 * (256 - DIV))
#
# ENV_CLOCK_HZ is inferred from COMPUTE.INTERP.NUMBERS (Synclavier II case):
# full-scale time T ms -> adder 256, divisor 0.75 T, i.e. one step per
# 0.75 T / N ms for N steps of full scale. The index envelope's full scale
# is 256 steps (limit = 2 x peak, peak < 128), giving 0.75 x 256 = 192
# steps per ms; the volume envelope's is 250 (limit = level/4, level 1000),
# giving 187.5. Uncertain to ~3 % until measured on hardware.

#: Interpolator input clock in Hz [INFERRED from NED's time -> rate code].
ENV_CLOCK_HZ = 192_000


def interp_rate(div, add):
    """Counter steps per second for hardware divisor/adder register values."""
    return ENV_CLOCK_HZ * ((add & 0o377) + 1) / (256 * (256 - (div & 0o377)))


def ned_interp_numbers(msec, range_, full):
    """NED COMPUTE.INTERP.NUMBERS for the Synclavier II (SYNTHTYP 0), linear
    case: the hardware (DIV, ADD) for a change of `range_` units, out of a
    full scale of `full` units, lasting `msec` ms. Also returns NED's
    exponential time constant TMC (16-bit fraction applied every 10 ms)."""
    t = msec * full
    t = 40000 if t >= range_ * 65536 else t // range_   # LOAD MSEC; MUL MAX; DIV RANGE
    divider = t - (t >> 2)
    adder = 256
    if divider == 0:
        divider = 1
    while divider > 257:
        divider >>= 1
        adder >>= 1
    if divider == 257:
        divider = 256
    div = 256 - divider
    add = adder - 1 if adder else 0
    m = 30000 if t >= 32768 else t                        # IF MSEC<0 THEN MSEC=30000
    m = max(m, 150)
    tmc = (65536 - (819200 // m)) & 0xFFFF               # TMC = -(819200/MSEC)
    return div & 0o377, add & 0o377, tmc


def exp_step(adder_word, tmc):
    """One 10 ms step of NED's exponential decay: EDAT = EDAT * TMC / 65536
    (unsigned fractional multiply); EADD = EDAT >> 8."""
    return (adder_word * tmc) >> 16


class Interpolator:
    """Prescaler + rate accumulator + up/down counter of one channel.

    Integer model of the structure above, advanced in whole clock ticks of
    ENV_CLOCK_HZ. `at_limit()` is the comparator that D160 bit 0 reports
    (inverted) while function 12 is selected: NED and Release L select the
    limit function, write the limit (twice, "for hardware accuracy") and
    read bit 0, 0 = limit reached.
    """

    def __init__(self):
        self.div = 0o377
        self.add = 0o377
        self.limit = 0
        self.value = 0
        self.prescale = 0      # clocks since the last prescaler pulse
        self.acc = 0           # 8-bit rate accumulator
        self.ticks = 0         # clocks consumed so far

    def advance_to(self, time_ns):
        target = time_ns * ENV_CLOCK_HZ // 1_000_000_000
        n = target - self.ticks
        if n <= 0:
            return
        self.ticks = target
        d = 256 - self.div
        total = self.prescale + n
        pulses, self.prescale = divmod(total, d)
        if not pulses:
            return
        steps, self.acc = divmod(self.acc + pulses * (self.add + 1), 256)
        if self.value < self.limit:
            self.value = min(self.limit, self.value + steps)
        elif self.value > self.limit:
            self.value = max(self.limit, self.value - steps)

    def write(self, fn, value, time_ns):
        self.advance_to(time_ns)
        if fn == 0o10:
            self.div = value & 0o377
        elif fn == 0o11:
            self.add = value & 0o377
        elif fn == 0o12:
            self.limit = value & 0o377

    def at_limit(self):
        return self.value == self.limit


# --- Shift count / pan, timbre bits, wave memory ---

def ishc(value):
    """Even-channel function 13: (pan, shift). Bits 7-2 are the stereo
    position (0 = all left, NED 600-INIT; 128 = centre), bits 1-0 the index
    shift count (303-SUB3: J = (STEREO & 374) + ISHC)."""
    return value & 0o374, value & 3


def modulation_offset(sample, index, shift):
    """Carrier phase offset (in waveform points, mod 256) from an unsigned
    8-bit modulator sample and an 8-bit index envelope value: the SS1 8x8
    multiplier, then the shifter selects bits 15-8 (shift 0) down to 12-5
    (shift 3), i.e. x1, x2, x4, x8 (card analysis)."""
    return ((sample & 0o377) * (index & 0o377) >> (8 - (shift & 3))) & 0o377


def wave_memory_number(tim):
    """Odd-channel function 4 (TIM): bits 4-0 select one of the 32 shared
    256-point wave memories (NED: TIM = 32 selects "WAVE MEM # 0"; splice
    memories are TIM = 48 + 8..15). Software always sets bit 5; its effect
    is not known."""
    return tim & 0o37


WAVE_MEMORIES = 32
