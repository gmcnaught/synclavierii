#!/usr/bin/env python3
"""HDL CPU (hdl/able_cpu.sv) in lockstep with the Python simulator (M4.3).

Needs Verilator (skipped otherwise). Random programs with random device
data and interrupts; with SYNCLAVIER_RELEASE_L set, also MONITOR's boot
and CATALOG.

Run:  python3 tests/hdl/test_lockstep.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.lockstep import check, random_cpu, record  # noqa: E402

HAVE_VERILATOR = shutil.which("verilator") is not None


def _check(cpu, n, **kw):
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        got = record(cpu, path, n, **kw)
        ok, text = check(path)
    finally:
        os.unlink(path)
    assert ok, text
    return got


def test_random_programs():
    if not HAVE_VERILATOR:
        print("  skip test_random_programs (verilator not found)")
        return
    for seed in range(60):
        assert _check(random_cpu(1000 + seed), 3000) == 3000   # Model B: ADC/SBB are no-ops


DEVICE_PROGRAM = """
        PCI TO R16
        DATA ENTRY
        PCI TO R5           ; input buffer for the interrupt handler
        DATA 4000
        IM(-10) TO D1       ; R17 is the PC, interrupts on
        PCI TO R4
        DATA 2000           ; 1024 passes
LOOP:   R4 TO D5            ; multiply: D5:D4 = R4 * 1234 + 0
        PCI TO D6
        DATA 1234
        D4 TO R0
        D5 TO R1
        R1 TO D5            ; divide (R4:R1) / 17: quotients above 16 bits
        R4 TO D4
        IM(17) TO D7
        D5 TO R2
        D4 TO R3
        R4 TO D60           ; external memory: sector R4 (1024 is beyond the end)
        PCI TO D61
        DATA 370
        R2 TO D63           ; 12 words across the sector boundary
        R3 TO D63
        R4 TO D63
        R0 TO D63
        R1 TO D63
        R2 TO D63
        R3 TO D63
        R4 TO D63
        R0 TO D63
        R1 TO D63
        R2 TO D63
        R3 TO D63
        R4 TO D60
        PCI TO D61
        DATA 376
        D63 TO R0           ; read back across the sector boundary
        D63 TO R1
        D63 TO R2
        D62 TO R2
        D60 TO R3           ; sector R4 + 1
        D61 TO R6
        R4 TO D50           ; send a character without waiting
        R4 TO R3            ; count down (arithmetic only on R0-R3)
        IM(1) TO SUB3
        R3 TO R4            ; register load keeps the flags
        PCI TO ATNZ         ; absolute transfer (LOOP is beyond relative range)
        DATA LOOP
        D50 TO R0           ; held until input arrives
        D50 TO R1
        D6 TO R0            ; D6 cannot be read: no SYN, halt
RETURN: IM(-10) TO D1
ENTRY:  D3 TO R7
        IM(0) TO D3         ; acknowledge the clock
        D51 TO R0
        IM(2) TO AND0
        RE(TTI) TO RTNZ
        IM(0) TO D51        ; acknowledge transmit
        RE(RETURN) TO RTRA
TTI:    D50 TO MR5I
        RE(RETURN) TO RTRA
"""


def test_system_devices_program():
    """The HDL devices (D3, D4567, D50/D51, D60-D63) against Python on a
    program that uses them all with interrupts, a held read and a halt."""
    if not HAVE_VERILATOR:
        print("  skip test_system_devices_program (verilator not found)")
        return
    from sim.asm import assemble
    from sim.system import make_system
    cpu = make_system()
    words, _ = assemble(DEVICE_PROGRAM)
    cpu.load(words)
    fed = []

    def on_wait(cpu):           # the handler may take characters too: feed again
        if len(fed) == 3:
            return False
        fed.append(1)
        cpu.terminal.feed("xyz")
        return True
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        n = record(cpu, path, 200_000, max_wait=4000, on_wait=on_wait)   # > 1 character time
        ok, text = check(path, top="system")
    finally:
        os.unlink(path)
    assert ok, text
    assert cpu.halted and cpu.halted.device == 0o6, cpu.halted
    assert n > 30_000 and cpu.rtc.ticks >= 5 and fed


def test_release_l_monitor_boot_and_catalog():
    image = os.environ.get("SYNCLAVIER_RELEASE_L")
    if not image or not HAVE_VERILATOR:
        print("  skip test_release_l_monitor_boot_and_catalog (needs SYNCLAVIER_RELEASE_L and verilator)")
        return
    from sim.boot import boot_from_image
    cpu, _ = boot_from_image(image, "03-SYSTD", f1="18-UTILS")
    lines = ["CATALOG\r"]

    def on_wait(cpu):
        if lines:
            cpu.terminal.feed(lines.pop(0))
            return True
        return False
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        n = record(cpu, path, 5_000_000, on_wait=on_wait)
        for top in ("cpu", "system"):
            ok, text = check(path, top=top)
            assert ok, (top, text)
    finally:
        os.unlink(path)
    assert n > 1_000_000 and "Catalog contains 7 entries" in cpu.terminal.text()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
