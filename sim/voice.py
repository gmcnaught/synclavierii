"""Original Synclavier II FM voices: integer voice model and audio (M3.2).

Replays the D162 register writes the CPU made (FMInterface.log: time_ns,
channel word, function, value) through a model of the voice cards and
renders audio. Register semantics: sim/fm.py and docs/fm-voice.md. The
model state is all integers, as in hardware; only the final mix is
floating point. Every structural assumption is marked:

  [OBS]      register semantics verified against Release L / NED source
  [INFERRED] narrow conclusion from NED source or the card analysis
  [CHOICE]   a modelling decision with no evidence yet (risk R1)

Per channel (even = modulator, odd = carrier):
  * Oscillator [INFERRED structure, OBS frequency]: each tick of
    OSC_CLOCK_HZ adds `increment` to an accumulator of modulus `divisor`;
    each wrap is a pulse; a 7-stage binary divider passes one pulse in
    2^(7 - ONU) to the 8-bit point counter (256 points per cycle). This
    gives f = K x 2^ONU x increment / divisor exactly (sim/fm.py), with
    OSC_CLOCK_HZ = 256 x 128 x K = 5.3335 MHz. The real clock tree is not
    known; only the resulting step rate is verified. The increment can
    exceed the divisor (A 440: 123 / 91; .STAB-6 ratios span about
    0.8-1.6), so at this clock a tick can produce two pulses; the real
    circuit must clock the accumulator faster or differently [UNKNOWN].
  * Interpolator: sim.fm.Interpolator (envelope on odd, index on even).

Per voice (channels 2v, 2v+1):
  modulator sample  m = SINE_ROM[mod point]                (8-bit unsigned)
  phase offset      o = (m x index) >> (8 - shift) & 255   (SS1, fm.modulation_offset)
  carrier sample    w = WAVE[TIM & 31][(car point + o) & 255]
  output            (w - 128) x envelope x VOL, panned by ISHC bits 7-2

  * Wave memory samples are unsigned, 0-255, centred on the DC point that
    NED's COMPUTE.WAVE keeps (a flat wave is 128) [OBS, 198-SYN2]; the DAC
    is taken as offset binary around 128 [CHOICE].
  * SINE_ROM: 256 points, round(127.5 + 127.5 sin(2 pi n / 256)) [CHOICE:
    the ROM is not dumped; NED's software sine table is centred the same
    way, 198-SYN2].
  * Envelope MDAC and volume DAC linear, 8 bits each [CHOICE].
  * Pan: linear, right = pan / 256, left = 1 - right (pan 0 = all left,
    128 = centre) [CHOICE: the 256 x 8 pan-law PROM is not dumped].

Output samples are taken at a fixed rate (rate x oversample) and box
filtered down to `rate`. On hardware each voice's DAC changes at its own
step rate (256 x f) and the analog stages filter it; that reconstruction is
not modelled.
"""
import math
import struct
from fractions import Fraction

from .fm import K_HZ, WAVE_MEMORIES, Interpolator, ishc, modulation_offset, \
    oscillator, wave_memory_number

#: Oscillator tick rate: the step rate at ONU 7, increment = divisor [INFERRED].
OSC_CLOCK = Fraction(256 * 128 * 440 * 91, 246)
assert abs(float(OSC_CLOCK) - 256 * 128 * K_HZ) < 1e-6
OCTAVE_STAGES = 7

#: Modulator waveform [CHOICE, see module docstring].
SINE_ROM = bytes(min(255, max(0, round(127.5 + 127.5 * math.sin(2 * math.pi * n / 256))))
                 for n in range(256))

FN_INC, FN_NNU, FN_ONU, FN_TIM, FN_ZMA, FN_MEM = 0, 1, 2, 4, 6, 7
FN_DIV, FN_ADD, FN_LIM, FN_13 = 0o10, 0o11, 0o12, 0o13


def osc_ticks(time_ns):
    """Whole oscillator ticks from time 0 to time_ns."""
    return time_ns * OSC_CLOCK.numerator // (OSC_CLOCK.denominator * 1_000_000_000)


class Oscillator:
    """Accumulator (modulus = divisor) + octave divider + 8-bit point counter."""

    def __init__(self):
        self.onu = self.nnu = self.inc = 0
        self.increment, self.divisor, self.octave = oscillator(0, 0, 0)
        self.acc = 0            # accumulator, 0 .. divisor-1
        self.prescale = 0       # octave divider count
        self.point = 0          # waveform address, 0-255
        self.ticks = 0

    def set(self, fn, value):
        if fn == FN_INC:
            self.inc = value & 0o377
        elif fn == FN_NNU:
            self.nnu = value & 0o377
        else:
            self.onu = value & 7
        self.increment, self.divisor, self.octave = oscillator(self.onu, self.nnu, self.inc)
        if self.acc >= self.divisor:
            self.acc %= self.divisor

    def advance(self, n):
        """Run n ticks (closed form of n single steps, see step())."""
        if n <= 0:
            return
        self.ticks += n
        pulses, self.acc = divmod(self.acc + n * self.increment, self.divisor)
        if pulses:
            points, self.prescale = divmod(self.prescale + pulses,
                                           1 << (OCTAVE_STAGES - self.octave))
            self.point = (self.point + points) & 0o377

    def step(self):
        """One tick, gate by gate (reference for advance() and for HDL)."""
        self.ticks += 1
        self.acc += self.increment
        while self.acc >= self.divisor:       # more than one pulse if increment > divisor
            self.acc -= self.divisor
            self.prescale += 1
            if self.prescale == 1 << (OCTAVE_STAGES - self.octave):
                self.prescale = 0
                self.point = (self.point + 1) & 0o377


class Channel:
    def __init__(self):
        self.osc = Oscillator()
        self.interp = Interpolator()
        self.tim = 0
        self.fn13 = 0           # ISHC (even) or VOL (odd)

    def advance_to(self, time_ns):
        self.osc.advance(osc_ticks(time_ns) - self.osc.ticks)
        self.interp.advance_to(time_ns)


class FMSynth:
    """Voice cards driven by D162 writes; renders stereo audio."""

    def __init__(self, voices=8):
        self.voices = voices
        self.ch = [Channel() for _ in range(2 * voices)]
        self.wave = [bytearray(256) for _ in range(WAVE_MEMORIES)]
        self.mar = [0] * (2 * voices)
        self.time_ns = 0

    def write(self, time_ns, channel_word, fn, value):
        """Apply one D162 write (FMInterface.log entry)."""
        c = channel_word & 0o377
        if c >= len(self.ch):
            return
        ch = self.ch[c]
        ch.advance_to(time_ns)
        if fn in (FN_INC, FN_NNU, FN_ONU):
            ch.osc.set(fn, value)
        elif fn == FN_TIM:
            ch.tim = value & 0o377
        elif fn == FN_ZMA:
            self.mar[c] = 0
        elif fn == FN_MEM:
            self.wave[wave_memory_number(ch.tim)][self.mar[c]] = value & 0o377
            self.mar[c] = (self.mar[c] + 1) & 0o377
        elif fn in (FN_DIV, FN_ADD, FN_LIM):
            ch.interp.write(fn, value, time_ns)
        elif fn == FN_13:
            ch.fn13 = value & 0o377

    def voice_sample(self, v):
        """Signed carrier output of voice v before volume and pan: (w - 128) x envelope.
        Channels must already be advanced."""
        mod, car = self.ch[2 * v], self.ch[2 * v + 1]
        env = car.interp.value
        if not env:
            return 0
        _, shift = ishc(mod.fn13)
        off = modulation_offset(SINE_ROM[mod.osc.point], mod.interp.value, shift)
        w = self.wave[wave_memory_number(car.tim)][(car.osc.point + off) & 0o377]
        return (w - 128) * env

    def sample_int(self, time_ns):
        """Integer output at time_ns: (sum of s x (256 - pan), sum of s x pan)
        over the voices, s = (w - 128) x envelope x VOL. This is what the
        HDL voice engine (hdl/dev/fm_voices.sv) computes."""
        left = right = 0
        for v in range(self.voices):
            mod, car = self.ch[2 * v], self.ch[2 * v + 1]
            car.interp.advance_to(time_ns)
            it = car.interp
            if it.value == 0 and it.limit == 0:
                continue                # silent until the next write to it
            mod.advance_to(time_ns)
            car.osc.advance(osc_ticks(time_ns) - car.osc.ticks)
            s = self.voice_sample(v) * car.fn13          # (w-128) x env x VOL
            if s:
                pan, _ = ishc(mod.fn13)
                right += s * pan
                left += s * (256 - pan)
        return left, right

    def sample(self, time_ns):
        """(left, right) at time_ns, full scale of one voice = 1.0."""
        left, right = self.sample_int(time_ns)
        return left / FULL_SCALE, right / FULL_SCALE

    def advance_all(self, time_ns):
        """Advance every channel to time_ns (closed form; no audible effect)."""
        for ch in self.ch:
            ch.advance_to(time_ns)


#: sample_int units per 1.0 of one voice: 128 x 256 (envelope) x 256 (VOL) x 256 (pan)
FULL_SCALE = 128 * 256 * 256 * 256


def render(log, start_ns=None, end_ns=None, rate=48_000, oversample=4, voices=8):
    """Replay `log` (time_ns, channel word, function, value) from its start
    and return stereo float samples [(l, r), ...] for start_ns..end_ns at
    `rate`. Writes before start_ns (wave memory loads) are applied first."""
    synth = FMSynth(voices)
    log = sorted(log, key=lambda e: e[0])
    if start_ns is None:
        start_ns = log[0][0] if log else 0
    if end_ns is None:
        end_ns = (log[-1][0] if log else 0) + 500_000_000
    sub = rate * oversample
    n = int((end_ns - start_ns) * sub // 1_000_000_000)
    out = []
    i = 0
    acc_l = acc_r = 0.0
    for k in range(n):
        t = start_ns + k * 1_000_000_000 // sub
        while i < len(log) and log[i][0] <= t:
            synth.write(*log[i])
            i += 1
        l, r = synth.sample(t)
        acc_l += l
        acc_r += r
        if k % oversample == oversample - 1:
            out.append((acc_l / oversample, acc_r / oversample))
            acc_l = acc_r = 0.0
    return out


def write_wav(path, samples, rate=48_000, gain=0.25):
    """16-bit stereo WAV. gain: full scale per voice (default 1/4, so four
    voices at full level reach full scale). Returns the number of clipped
    samples."""
    clipped = 0
    frames = bytearray()
    for l, r in samples:
        for x in (l, r):
            y = int(round(x * gain * 32767))
            if y > 32767 or y < -32768:
                clipped += 1
                y = max(-32768, min(32767, y))
            frames += struct.pack("<h", y)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, rate, rate * 4, 4, 16))
        f.write(b"data" + struct.pack("<I", len(frames)) + frames)
    return clipped


def read_fm_csv(path):
    """FM log from `sim.rtp --fm-log` CSV."""
    import csv
    with open(path) as f:
        return [(int(r["time_ns"]), int(r["channel_word"], 8), int(r["function"], 8),
                 int(r["value"], 8)) for r in csv.DictReader(f)]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Render a D162 write log (sim.rtp --fm-log CSV) to WAV")
    ap.add_argument("csv")
    ap.add_argument("wav")
    ap.add_argument("--rate", type=int, default=48_000)
    ap.add_argument("--oversample", type=int, default=4)
    ap.add_argument("--gain", type=float, default=0.25)
    a = ap.parse_args(argv)
    samples = render(read_fm_csv(a.csv), rate=a.rate, oversample=a.oversample)
    clipped = write_wav(a.wav, samples, a.rate, a.gain)
    print("%s: %.2f s, %d clipped" % (a.wav, len(samples) / a.rate, clipped))


if __name__ == "__main__":
    raise SystemExit(main())
