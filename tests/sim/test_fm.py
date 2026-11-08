#!/usr/bin/env python3
"""Tests for sim/fm.py (FM register semantics, M3.1a). Stdlib only.

Run:  python3 tests/sim/test_fm.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.fm import K_HZ, frequency, log_frequency_hz, oscillator, registers  # noqa: E402


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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
