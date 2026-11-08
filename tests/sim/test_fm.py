#!/usr/bin/env python3
"""Tests for sim/fm.py (FM register semantics, M3.1a). Stdlib only.

Run:  python3 tests/sim/test_fm.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.fm import (ENV_CLOCK_HZ, K_HZ, Interpolator, exp_step, frequency, interp_rate,  # noqa: E402
                    ishc, log_frequency_hz, modulation_offset, ned_interp_numbers,
                    oscillator, registers, wave_memory_number)


def test_patent_encoding():
    # US 4,345,500: Do = (256 - Divisor) + (Increment - 1/16); NED: NNU = 256 - div + INC>>3
    onu, nnu, inc = registers(increment=16, divisor=193, octave=0)
    assert (onu, nnu, inc) == (0, 256 - 193 + (15 >> 3), 15)
    assert oscillator(onu, nnu, inc) == (16, 193, 0)
    # lowest frequency in COMPUTE.OSYN.FREQ: inc 5, div 199 -> INC 4, NNU 57
    assert registers(5, 199, 0) == (0, 57, 4)


def test_release_l_pitches():
    # register values written by Release L ORK-LM (timbre 0 of 06-TIMBD bank 0)
    cases = {36: (1, 159, 85, 261.63), 45: (1, 180, 122, 440.0), 57: (1, 238, 72, 880.0),
             60: (1, 239, 89, 1046.5), 72: (2, 239, 89, 2093.0)}
    for key, (onu, nnu, inc, hz) in cases.items():
        assert abs(frequency(onu, nnu, inc) / hz - 1) < 0.001, (key, frequency(onu, nnu, inc))


def test_log_frequency():
    assert log_frequency_hz(2816) == 440.0
    assert abs(log_frequency_hz(2816 + 1024) - 880.0) < 1e-9
    assert abs(K_HZ * 2 * 123 / 91 - 440.0) < 1e-9


def test_ned_interp_numbers():
    # attack 0: fastest rate (Release L ORK-LM writes EDIV 377, EADD 377)
    assert ned_interp_numbers(0, 1000, 1000)[:2] == (255, 255)
    # NED's times come out within a few % of the inferred clock
    for msec, rng, full, steps in ((1000, 1000, 1000, 250), (100, 500, 1000, 125),
                                   (3000, 1000, 1000, 250), (500, 64, 128, 128)):
        div, add, _ = ned_interp_numbers(msec, rng, full)
        t = steps / interp_rate(div, add)
        assert abs(t / (msec / 1000) - 1) < 0.04, (msec, rng, div, add, t)


def test_release_l_exponential_decay():
    # ORK-LM, timbre 0 key C4 released: EADD every 10 ms
    seen = [255, 233, 214, 196, 180, 165, 151, 138, 127, 116, 106, 97]
    tmc = ned_interp_numbers(0, 1000, 1000)[2]       # minimum time constant, 150 ms
    edat, got = 255 << 8, []
    for _ in seen:
        got.append(edat >> 8)
        edat = exp_step(edat, tmc)
    assert got == seen, got


def _ns(clocks):
    return -(-clocks * 1_000_000_000 // ENV_CLOCK_HZ)


def test_interpolator():
    it = Interpolator()
    it.write(0o10, 0o377, 0)                         # divisor 1
    it.write(0o11, 0o177, 0)                         # adder 128: one step per 2 clocks
    it.write(0o12, 100, 0)
    assert not it.at_limit() and interp_rate(0o377, 0o177) == ENV_CLOCK_HZ / 2
    it.advance_to(_ns(10))                           # 10 clocks
    assert it.value == 5
    it.advance_to(10**9)
    assert it.value == 100 and it.at_limit()          # stops at the limit
    it.write(0o10, 0o376, 10**9)                      # divisor 2, adder 256
    it.write(0o11, 0o377, 10**9)
    it.write(0o12, 40, 10**9)                         # counts down
    it.advance_to(10**9 + _ns(20))
    assert it.value == 90
    it.advance_to(2 * 10**9)
    assert it.value == 40 and it.at_limit()


def test_ishc_modulation_and_wave_memory():
    assert ishc(0o203) == (128, 3)                   # Release L note-on: centre, shift 3
    assert ishc(0) == (0, 0)                         # 600-INIT: "ALL LEFT"
    assert modulation_offset(255, 255, 0) == 254     # card analysis: 255*255/256
    assert modulation_offset(255, 255, 3) == (255 * 255 >> 5) & 255
    assert modulation_offset(128, 64, 1) == 64
    assert wave_memory_number(32) == 0 and wave_memory_number(0o44) == 4
    assert wave_memory_number(48 + 13) == 29         # splice memory 13


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
