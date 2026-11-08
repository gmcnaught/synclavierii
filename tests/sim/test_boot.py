#!/usr/bin/env python3
"""Tests for sim/boot.py (M1.6 step A high-level boot), stdlib only.

The synthetic tests use a small XPL-shaped program and a stand-in loader
whose entry 4 copies from external memory like FLPLOAD's ECOPY.

If SYNCLAVIER_RELEASE_L points to the user-supplied Release L .simg, the
real MONITOR is booted as well (skipped otherwise; the image is not in the
repository).

Run:  python3 tests/sim/test_boot.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.asm import assemble  # noqa: E402
from sim.boot import boot, boot_from_image, mem_size  # noqa: E402
from sim.system import make_system  # noqa: E402

# Loader stand-in: five-entry relative jump vector; entry 4 = ECOPY
# (R0 = ext-memory sector, R1 = destination, R2 = length), then start at 0.
LOADER = """
        RE(HANG) TO RTRA
        RE(HANG) TO RTRA
        RE(HANG) TO RTRA
        RE(HANG) TO RTRA
        RE(ECOPY) TO RTRA
HANG:   RE(HANG) TO RTRA
ECOPY:  IM(-20) TO D1
        R0 TO D60
COPY:   D63 TO MR1I
        IM(1) TO SUB2
        RE(COPY) TO RTNZ
        IM(0) TO ATRA
"""

# XPL-shaped program: word 0 PCI TO LOA0, word 1 = config pointer;
# config entry 16 = memory size in sectors (360 = 60K words).
PROGRAM = """
        PCI TO LOA0
        DATA CFG
        IM(7) TO D50
DONE:   RE(DONE) TO RTRA
CFG:    DATA 0
""" + "        DATA 0\n" * 15 + "        DATA 360\n"


def test_mem_size_from_config():
    prog, _ = assemble(PROGRAM)
    assert mem_size(prog) == 0o170000
    bad = list(prog)
    bad[0] = 0
    try:
        mem_size(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("non-XPL program accepted")


def test_boot_runs_loader_ecopy_and_starts_program():
    prog, labels = assemble(PROGRAM)
    loader, _ = assemble(LOADER)
    cpu = make_system()
    cpu.mem[0:len(prog)] = [0] * len(prog)
    lay = boot(cpu, prog, loader, staging_sector=5)
    assert lay["loc_load"] == 0o166000
    assert cpu.pc == 0o166004
    assert cpu.mem[0o166000:0o166000 + len(loader)] == loader
    for _ in range(10_000):
        if cpu.pc == labels["DONE"]:
            break
        assert cpu.step(), cpu.halted
    assert cpu.mem[:len(prog)] == prog          # copied from sector 5
    assert cpu.terminal.out == bytearray([7])


def test_release_l_monitor_banner():
    image = os.environ.get("SYNCLAVIER_RELEASE_L")
    if not image:
        print("  skip test_release_l_monitor_banner (SYNCLAVIER_RELEASE_L not set)")
        return
    cpu, lay = boot_from_image(image)
    assert lay["mem_siz"] == 0o170000
    cpu.run(5_000_000)
    assert "N.E.D. ABLE Series System Monitor" in cpu.terminal.text()
    # cold boot restores the F0 head next: needs the D100 floppy (step B)
    assert cpu.halted and cpu.halted.device == 0o100


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
