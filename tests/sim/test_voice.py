#!/usr/bin/env python3
"""Tests for sim/voice.py (M3.2: integer FM voice model and audio).

Run:  python3 tests/sim/test_voice.py
"""
import math
import os
import random
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.fm import Interpolator, frequency, registers  # noqa: E402
from sim.voice import (OSC_CLOCK, SINE_ROM, FMSynth, Oscillator, osc_ticks,  # noqa: E402
                       render, write_wav)

RATE = 48_000
MS = 1_000_000


def goertzel(x, f, rate=RATE):
    w = 2 * math.pi * f / rate
    re = sum(v * math.cos(w * i) for i, v in enumerate(x))
    im = sum(v * math.sin(w * i) for i, v in enumerate(x))
    return 2 * math.hypot(re, im) / len(x)


def sine_wave():
    return [SINE_ROM[n] for n in range(256)]


def note(log, t, voice, regs, wave_mem=4, env=250, vol=255, ishc=0o200, index=0):
    """Writes for a held note on `voice`: wave memory, pitch, envelope."""
    mod, car = 2 * voice, 2 * voice + 1
    onu, nnu, inc = regs
    for ch in (mod, car):
        log += [(t, ch, 2, onu), (t, ch, 1, nnu), (t, ch, 0, inc)]
    log += [(t, mod, 0o13, ishc), (t, mod, 0o10, 0o377), (t, mod, 0o11, 0o377), (t, mod, 0o12, index),
            (t, car, 4, 32 + wave_mem), (t, car, 0o13, vol),
            (t, car, 0o10, 0o377), (t, car, 0o11, 0o377), (t, car, 0o12, env)]


def load_wave(log, t, ch, mem, points):
    log += [(t, ch, 4, 32 + mem), (t, ch, 6, 0)] + [(t, ch, 7, p) for p in points]


def test_oscillator_closed_form_matches_steps():
    rng = random.Random(1)
    for _ in range(40):
        a, b = Oscillator(), Oscillator()
        for fn in (0, 1, 2):
            v = rng.randrange(256)
            a.set(fn, v)
            b.set(fn, v)
        for n in (1, 7, rng.randrange(1, 3000)):
            a.advance(n)
            for _ in range(n):
                b.step()
            assert (a.acc, a.prescale, a.point) == (b.acc, b.prescale, b.point), (a.__dict__, b.__dict__)


def test_oscillator_rate_is_pitch_formula():
    for regs in ((1, 192, 126), (1, 180, 122), (2, 239, 89), (0, 0, 0)):
        o = Oscillator()
        for fn, v in zip((2, 1, 0), regs):
            o.set(fn, v)
        n = osc_ticks(1_000_000_000)            # one second
        o.advance(n)
        increment, divisor, octave = o.increment, o.divisor, o.octave
        cycles = (n * increment // divisor >> (7 - octave)) / 256
        assert abs(cycles - frequency(*regs)) < 1.0 / 256 + 1e-9 + frequency(*regs) * 1e-6
        assert o.point == (n * increment // divisor >> (7 - octave)) & 255
    assert abs(float(OSC_CLOCK) - 5_333_458) < 1


def test_interpolator_closed_form_matches_steps():
    """Interpolator.advance_to (closed form) against a clock-by-clock model."""
    rng = random.Random(2)
    for _ in range(30):
        it = Interpolator()
        div, add, lim, start = (rng.randrange(256) for _ in range(4))
        it.value = start
        it.write(0o10, div, 0)
        it.write(0o11, add, 0)
        it.write(0o12, lim, 0)
        value, pre, acc = start, 0, 0
        for clocks in (1, 5, rng.randrange(1, 4000)):
            for _ in range(clocks):
                pre += 1
                if pre == 256 - div:
                    pre = 0
                    acc += add + 1
                    if acc >= 256:
                        acc -= 256
                        if value != lim:
                            value += 1 if value < lim else -1
            ticks = it.ticks + clocks
            it.advance_to(-(-ticks * 1_000_000_000 // 192_000))
            assert (it.value, it.prescale, it.acc) == (value, pre, acc)


def test_pure_wave_pitch_and_level():
    log = []
    load_wave(log, 0, 15, 4, sine_wave())
    regs = registers(126, 64, 1)                # some note, f = K * 2 * 126 / 64
    note(log, MS, 0, regs)
    s = render(log, 0, 300 * MS, rate=RATE, oversample=1)
    x = [l + r for l, r in s[RATE // 10:]]      # skip the attack
    f = frequency(*regs)
    a = goertzel(x, f)
    expect = 127.5 / 128 * 250 / 256 * 255 / 256   # (w-128) x env x VOL, centre pan sums to 1
    assert abs(a / expect - 1) < 0.01, (a, expect)
    assert goertzel(x, 2 * f) < 0.01 * a and goertzel(x, 3 * f) < 0.01 * a


def test_fm_sidebands():
    """Modulator = carrier frequency, constant index: harmonics appear and
    grow with the index; index 0 gives the pure carrier wave."""
    regs = registers(126, 64, 1)
    f = frequency(*regs)
    levels = []
    for index, shift in ((0, 0), (128, 0), (255, 1)):
        log = []
        load_wave(log, 0, 15, 4, sine_wave())
        note(log, MS, 0, regs, index=index, ishc=0o200 | shift)
        s = render(log, 0, 200 * MS, rate=RATE, oversample=1)
        x = [l + r for l, r in s[RATE // 20:]]
        levels.append([goertzel(x, k * f) for k in (1, 2, 3)])
    assert levels[0][1] < 0.01 * levels[0][0]
    assert levels[1][1] > 0.2 * levels[1][0]
    assert levels[2][2] > levels[1][2] > levels[0][2]


def test_fm_path_matches_definition():
    """One voice's sample equals the spec formula at arbitrary instants."""
    from sim.fm import modulation_offset
    synth = FMSynth(1)
    wave = [random.Random(3).randrange(256) for _ in range(256)]
    for e in ([(0, 1, 4, 32 + 9), (0, 1, 6, 0)] + [(0, 1, 7, p) for p in wave]):
        synth.write(*e)
    log = []
    note(log, 0, 0, registers(100, 80, 2), wave_mem=9, index=200, ishc=0o200 | 2)
    log.append((0, 0, 1, 70))                  # modulator at a different pitch
    for e in log:
        synth.write(*e)
    for t in (3 * MS, 7 * MS + 123, 50 * MS):
        for ch in synth.ch:
            ch.advance_to(t)
        mod, car = synth.ch
        off = modulation_offset(SINE_ROM[mod.osc.point], mod.interp.value, 2)
        w = wave[(car.osc.point + off) & 255]
        assert synth.voice_sample(0) == (w - 128) * car.interp.value


def test_pan_and_silence():
    log = []
    load_wave(log, 0, 15, 4, sine_wave())
    note(log, MS, 0, registers(126, 64, 1), ishc=0)          # pan 0 = all left
    s = render(log, 0, 100 * MS, rate=RATE, oversample=1)
    assert max(abs(l) for l, r in s) > 0.5 and max(abs(r) for l, r in s) == 0
    log.append((100 * MS, 1, 0o12, 0))                        # envelope limit 0
    s = render(log, 0, 200 * MS, rate=RATE, oversample=1)
    assert all(l == 0 for l, r in s[-RATE // 20:])


def test_write_wav():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        clipped = write_wav(path, [(0.0, 1.0), (-1.0, 8.0)], rate=RATE, gain=1.0)
        data = open(path, "rb").read()
    finally:
        os.unlink(path)
    assert clipped == 1 and data[:4] == b"RIFF" and data[8:16] == b"WAVEfmt "
    assert struct.unpack("<IHHIIHH", data[16:36]) == (16, 1, 2, RATE, RATE * 4, 4, 16)
    assert struct.unpack("<4h", data[44:]) == (0, 32767, -32767, 32767)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
