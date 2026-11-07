#!/usr/bin/env python3
"""Self-test for tools/able_disasm.py (stdlib only).

Run:  python3 tests/test_able_disasm.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import able_disasm as A  # noqa: E402

LISTING = os.path.join(HERE, "fixtures", "NED-SCSI.LST")


def test_listing_matches():
    assert A.validate(LISTING, "B"), "decoder disagrees with NED assembler listing"


def test_relative_targets():
    text = open(LISTING, "rb").read().decode("latin-1").replace("\r", "\n").splitlines()
    labels, refs = {}, []
    for ln in text:
        m = re.match(r"^\s+([0-7]{6})\s+([0-7]{6})\s+\d+\s+(\S+):\s", ln)
        if m:
            labels[m.group(3)] = int(m.group(1), 8)
        m = re.match(r"^\s+([0-7]{6})\s+([0-7]{6})\s+\d+\s+(?:\S+:\s+)?RE\(([A-Z0-9.]+)\)\s+TO", ln)
        if m:
            refs.append((int(m.group(1), 8), int(m.group(2), 8), m.group(3)))
    n = 0
    for addr, w, lab in refs:
        if lab in labels:
            _, _, _, v, _ = A.disasm_word(w, "B")
            assert addr + 1 + v == labels[lab], (oct(addr), lab)
            n += 1
    assert n > 50
    print("relative targets checked:", n)


def test_known_words():
    cases = {
        0o175304: ("R4", "MR12D"),     # Model C push
        0o150010: ("D10", "ATRA"),     # return via D10 link
        0o004301: ("R1", "D10"),       # RPT count
        0o000660: ("IM(-20)", "D1"),   # PCW: disable interrupts (octal immediate)
        0o154215: ("IM(15)", "RTRA"),
        0o134302: ("R2", "ADC0"),
        0o137302: ("R2", "SBB2"),
    }
    for w, (s, d) in cases.items():
        st, dt, *_ = A.disasm_word(w, "C")
        assert (st, dt) == (s, d), (oct(w), st, dt)
    assert A.disasm_word(0o175304, "B")[1] == "MR12I"  # alias only on Model C+


if __name__ == "__main__":
    test_known_words()
    test_relative_targets()
    test_listing_matches()
    print("OK")
