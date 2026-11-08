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
    n = _check(cpu, 5_000_000, on_wait=on_wait)
    assert n > 1_000_000 and "Catalog contains 7 entries" in cpu.terminal.text()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
