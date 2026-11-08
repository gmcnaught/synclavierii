#!/usr/bin/env python3
"""Tests for sim/trace.py (M1.7 debug tooling), stdlib only.

Run:  python3 tests/sim/test_trace.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.asm import assemble  # noqa: E402
from sim.system import make_system  # noqa: E402
from sim.trace import STOP_BREAKPOINT, STOP_HALTED, Debugger  # noqa: E402

PROG = """
        IM(3) TO R1
LOOP:   IM(1) TO SUB1
        RE(LOOP) TO RTNZ
        IM(7) TO D50        ; terminal: bell
        D51 TO R2           ; terminal status
        D100 TO R3          ; no floppy attached: no SYN
DONE:   RE(DONE) TO RTRA
"""


def setup():
    cpu = make_system()
    words, labels = assemble(PROG)
    cpu.load(words, 0)
    return cpu, labels, Debugger(cpu, history_len=4, io_len=8)


def test_halt_report_names_device_and_history():
    cpu, labels, dbg = setup()
    assert dbg.run(1000) == STOP_HALTED
    assert cpu.halted.device == 0o100
    assert len(dbg.history) == 4                      # ring buffer bound
    assert dbg.history[-1] == (labels["DONE"] - 1, cpu.mem[labels["DONE"] - 1])
    kinds = [(k, d) for _, k, d, _ in dbg.io]
    assert kinds == [("W", 0o50), ("R", 0o51), ("R", 0o100)]
    assert dbg.io[-1][3] is None                      # NO SYN recorded
    rep = dbg.report()
    assert "no SYN on read" in rep and "device D100" in rep
    assert "D100     TO R3" in rep                    # disassembled history
    assert "NO SYN" in rep


def test_breakpoint_stops_before_fetch_and_resumes():
    cpu, labels, dbg = setup()
    dbg.breakpoints.add(labels["LOOP"])
    assert dbg.run(1000) == STOP_BREAKPOINT
    assert cpu.pc == labels["LOOP"] and cpu.r[1] == 3
    assert dbg.run(1000) == STOP_BREAKPOINT          # stepped over, next pass
    assert cpu.r[1] == 2
    dbg.breakpoints.clear()
    assert dbg.run(1000) == STOP_HALTED


def test_budget_and_detach():
    cpu, labels, dbg = setup()
    assert dbg.run(2) is None and cpu.instructions == 2
    dbg.detach()
    assert cpu.trace is None
    assert "read" not in vars(cpu.bus)               # bus methods restored
    cpu.run(1000)
    assert len(dbg.history) == 2                     # nothing recorded after detach


def test_memory_inspect():
    cpu, labels, dbg = setup()
    assert dbg.memory(0, 2).startswith("000000: ")
    assert "IM(3)    TO R1" in dbg.memory(0, 1, disasm=True)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
