"""Original Synclavier II FM synthesizer: register semantics (M3.1a).

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
