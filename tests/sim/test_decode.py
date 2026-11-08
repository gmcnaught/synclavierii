#!/usr/bin/env python3
"""The simulator's decode tables agree with tools/able_disasm.py, and the
test assembler is the exact inverse of the disassembler (stdlib only).

Run:  python3 tests/sim/test_decode.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim import decode as D  # noqa: E402
from sim.asm import assemble  # noqa: E402
from tools import able_disasm as A  # noqa: E402

SRC_KIND = {D.S_IO: "io", D.S_IMM: "imm", D.S_REG: "reg", D.S_REGI: "reg",
            D.S_MEM: "mem", D.S_MEMI: "mem"}
DST_KIND = {D.D_IO: "io", D.D_ALU: "alu", D.D_TEST: "test", D.D_BSOR: "ext",
            D.D_SHRA: "ext", D.D_ADC: "ext_c", D.D_SBB: "ext_c", D.D_REG: "reg",
            D.D_JABS: "jabs", D.D_JREL: "jrel", D.D_MEM: "mem", D.D_MEMI: "mem"}


def test_source_table():
    for s in range(256):
        cls, v = D.SRC_TABLE[s]
        text, kind, av = A.decode_src(s)
        assert SRC_KIND[cls] == kind, oct(s)
        if cls == D.S_IMM:
            assert v == av & 0xFFFF, oct(s)
        else:
            assert v == av, oct(s)
        assert text.endswith("I") == (cls in (D.S_REGI, D.S_MEMI)) or text == "PCI", oct(s)


def test_destination_table():
    for d in range(256):
        cls, a, b = D.DST_TABLE[d]
        text, kind = A.decode_dst(d, "B")
        assert DST_KIND[cls] == kind, oct(d)
        if cls == D.D_ALU:
            assert text == A.ACC_OPS[a] + str(b)
        if cls == D.D_TEST:
            assert text == A.TEST_OPS[a] + str(b)
        if cls in (D.D_JABS, D.D_JREL):
            assert text[1:] == A.COND[a]


def test_assembler_round_trip():
    lines, words = [], []
    for w in range(0x10000):
        st, dt, *_ = A.disasm_word(w, "B")
        lines.append("%s TO %s" % (st, dt))
        words.append(w)
    got, _ = assemble("\n".join(lines))
    assert got == words


if __name__ == "__main__":
    test_source_table()
    test_destination_table()
    test_assembler_round_trip()
    print("OK")
