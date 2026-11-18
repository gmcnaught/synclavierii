#!/usr/bin/env python3
"""tools/synx.py: Synclavier V (.synx) presets -> NED timbre records.

The table tests need nothing else. test_system_disk needs the git-ignored
`timbres/Synclavier II Timbres/` and `timbres/fm-download/` folders and
skips without them.
"""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from tools import synx, stmb  # noqa: E402

SYNX_DIR = os.path.join(ROOT, "timbres", "Synclavier II Timbres")
TEXT_DIR = os.path.join(ROOT, "timbres", "fm-download", "Original NED FM Timbre Libraries")


def test_tables():
    d = synx.DEC
    # values taken from presets and their Regen text
    assert d["time"](0.6) == 1.0 and d["time"](0.136) == 0.034 and d["time"](0.92) == 15.0
    assert d["pct"](0.8) == 50.0 and d["pct"](0.7024) == 37.8
    assert d["idx"](0.416) == 128 and d["idx"](1.0) == 1000
    assert d["hz"](0.4) == 5.0 and d["hz"](0.6) == 10.0
    assert d["semi"](0.4) == 1.0 and d["semi"](0.96) == 20.0
    assert d["octave"](0.75) == 440.0 and d["octave"](0.625) == 220.0
    assert d["cents"](0.5448) == 11.2 and d["semis"](0.6458333) == 7.0
    assert d["ratio"](0.1125) == 1.8 and d["fine"](0.725) == 0.045
    assert d["db"](0.0) is None and d["db"](0.746) == -12.7
    assert d["pct100"](0.76) == 82.0 and d["pct100"](0.5) == 50.0
    assert d["deg"](0.0) == 0.0 and d["deg"](0.5) == 180.0
    assert synx.coeff(0.984) == 96.0 and synx.coeff(0.5402812361717224) == 19.6
    assert [synx.phase(synx.PHASE_TABLE[k]) for k in range(64)] == [k * 5.625 for k in range(64)]
    assert len(synx.PCT100) == 251 and synx.PCT100[125] == 50.0 and synx.PCT100[-1] == 100.0
    assert synx.DEG360[125] == 180 and synx.DEG360[126] == -179 and synx.DEG360[-1] == 0


def test_system_disk():
    bank = os.path.join(SYNX_DIR, "Synclavier_Bank_System Disk Timbres.synx")
    if not os.path.exists(bank) or not os.path.isdir(TEXT_DIR):
        print("  skip test_system_disk (timbres/ not present)")
        return
    # harmonic and frame blocks agree with the Regen text
    assert synx.cmd_verify(bank, os.path.join(TEXT_DIR, "System Disk")) == 0
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "s.stmb")
        assert synx.cmd_convert(bank, out, os.path.join(d, "r.txt"), 2000) == 0
        _, _, banks = stmb.read_banks(out)
    organ = banks[0][2]                                  # 1213 - ORGAN
    assert organ["name"].startswith("ORGAN")
    w = organ["partials"][0]["params"]
    assert [w[12 + i] & 1023 for i in range(8)] == [1000, 1000, 1000, 1000, 0, 0, 0, 960]
    assert w[36] == 2200 and w[3] == 150                 # 220 Hz, final decay 0.15 s
    # FM off (Partial Modulation 0): no index envelope
    assert w[10] == 0 and w[11] == 0
    # --regen adds the text's real-time effects: 17 System Disk entries have them
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "s.stmb")
        assert synx.cmd_convert(bank, out, os.path.join(d, "r.txt"), 2000,
                                os.path.join(TEXT_DIR, "System Disk")) == 0
        _, _, merged = stmb.read_banks(out)
    rte = [t for bk in merged for t in bk if t and t.get("tinfo")
           and t["tinfo"][16:56] != [15, 0, 0, 0, 0] * 8]
    assert rte


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
