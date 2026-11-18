#!/usr/bin/env python3
"""tools/sample_pitch.py: the pitch measurement on synthetic tones, the
name-group resolution, and the PT.TRA correction rules. Standard library
only; no sound files.

Run:  python3 tests/test_sample_pitch.py
"""
import math
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from tools import sample_pitch as sp  # noqa: E402

RATE = 50000


def tone(key, amps, seconds=0.5):
    """Harmonic tone: amps[h-1] for harmonic h."""
    f0 = 440 * 2 ** ((key - 69) / 12)
    n = int(seconds * RATE)
    return [int(sum(a * math.sin(2 * math.pi * f0 * h * i / RATE) for h, a in enumerate(amps, 1) if f0 * h < RATE / 2))
            for i in range(n)]


def test_measure():
    key, margin = sp.measure(tone(69, [8000, 4000, 2000, 1000]), RATE)
    assert key == 69 and margin >= sp.MIN_MARGIN, (key, margin)
    # weak fundamental, strong 2nd harmonic (a low piano note): still the fundamental
    key, margin = sp.measure(tone(40, [600, 9000, 5000, 4000, 3000, 2000, 1500, 1000]), RATE)
    assert key == 40, (key, margin)
    assert sp.measure([0] * 30000, RATE) is None


def test_names():
    assert sp.name_key("PNOA#540") == 82 and sp.name_key("TPTEN440") == 64
    assert sp.name_pitch_class("SYNCN441") == 0 and sp.name_key("BDR-50") is None
    assert sp.name_group("PNOA#540") == "PNO?40" and sp.name_group("PNOEN171") == "PNO?71"


def test_resolve():
    rows = [("PNOA#140", 34, 0.3, RATE), ("PNOA#240", 46, 0.3, RATE), ("PNOA#340", 58, 0.3, RATE),
            ("PNOEN240", 52, 0.04, RATE),          # unsure octave: the group says recorded = name
            ("PNOEN340", 52, 0.4, RATE),
            ("TPTA#440", 82, 0.35, RATE),          # recorded an octave above its name
            ("XYZ123", 60, 0.5, RATE),             # no note in the name: as measured
            ("CHIF#340", 61, 0.02, RATE)]          # unsure, no group evidence
    r = sp.resolve(rows)
    assert r["PNOA#140"] == (34, "measured") and r["PNOEN240"][0] == 40
    assert r["PNOEN240"][1].startswith("group PNO?40")
    assert r["TPTA#440"] == (82, "measured") and r["XYZ123"] == (60, "measured")
    assert r["CHIF#340"][1] == "unsure"


def test_correction():
    table = {"PNOA#540": (82, "measured"), "TPTA#440": (82, "measured"), "PNOEN240": (40, "group")}
    # PT.TRA key 70 (+24 = MIDI 94) but recorded 82: move the key down 12
    assert sp.correction("PNOA#540", 70 | 256, 0, table) == (-12, "ok")
    assert sp.correction("TPTA#440", 58, 0, table) == (0, "in tune")
    assert sp.correction("PNOEN240", 28, 0, table) == (-12, "ok")
    assert sp.correction("PNOA#540", 0, 0, table) == (0, "no transposition")
    assert sp.correction("PNOA#540", 65, 0, table)[0] == 0              # 7 semitones: not an octave
    assert sp.correction("PNOA#540", 70, 100, table)[0] == 0            # PT.TUN +1 semitone: 83 != 82 +- 12
    assert sp.correction("NOTHERE", 70, 0, table) == (0, "not settled")


def test_correct_timbre_and_table():
    name = [ord(c) for c in "PNOA#540"]
    words = [name[k] | name[k + 1] << 8 for k in range(0, 8, 2)]
    frame = [0xFFFF, 1, 48] + words + [66, 72, 1000, 70 | 256, 0] + [0] * 36
    t = {"name": "FULL PIANO", "partials": [{"params": [0] * 46, "frames": [frame]}, None, None, None]}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.tsv")
        sp.write_table([("PNOA#540", 82, 0.17, RATE), ("PNOA#140", 34, 0.22, RATE)], path)
        table = sp.read_table(path)
    log = []
    assert sp.correct_timbre(t, table, log) == 1
    assert frame[sp.PT_TRA] == 58 | 256 and log == [("FULL PIANO", "PNOA#540", 58, -12, "ok")]
    assert sp.correct_timbre(t, table) == 0                              # now in tune


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
