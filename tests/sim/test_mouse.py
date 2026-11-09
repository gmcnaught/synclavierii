#!/usr/bin/env python3
"""The D44/D45/D54 mouse model (sim/devices/mouse.py), the VT640 graphics
reference (tools/vt100.py Terminal(vt640=True)) and, with SYNCLAVIER_W0
set, SYN-5.3 configured for a VT640 with a mouse.

Run:  python3 tests/sim/test_mouse.py
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from sim.devices.mouse import BYTE_NS, IRQ_BIT, Mouse  # noqa: E402
from tools.vt100 import Terminal, tek_to_pixel  # noqa: E402


def drain(m, n):
    got = []
    for _ in range(n):
        m.tick(BYTE_NS)
        assert m.read(0o45) == 2
        got.append(m.read(0o44))
        assert m.read(0o45) == 0
    return got


def test_status_and_report():
    m = Mouse()
    m.write(0o44, 0)
    m.write(0o44, 0o104)                       # D: no reply
    m.write(0o44, 0o163)                       # s
    m.tick(BYTE_NS - 1)
    assert m.read(0o45) == 0
    assert drain(m, 1) == [0o117]
    m.move(127, -30)                           # two packets: 200 right, 30 down
    m.move(73, 0)
    m.set_buttons(left=True)
    m.write(0o44, 0o120)                       # P
    assert drain(m, 3) == [0o200 | 0o20 | 0o4, 127, 30]
    m.write(0o44, 0o120)                       # the rest of the motion (127 + 73)
    assert drain(m, 3) == [0o200 | 0o20 | 0o10 | 0o4, 73, 0]


def test_interrupt():
    m = Mouse()
    m.write(0o44, 0o163)
    m.tick(BYTE_NS)
    assert m.irq_bits() == 0 and m.read(0o54) == 0
    m.write(0o54, 4)
    assert m.irq_bits() == IRQ_BIT and m.read(0o54) == 4
    m.write(0o45, 0)                           # keeps receive-ready
    assert m.read(0o45) == 2
    m.read(0o44)
    assert m.irq_bits() == 0


def test_tek_reference():
    assert all(tek_to_pixel(x * 1023 // 639, y * 779 // 479) == (x, y)
               for x in range(0, 640, 7) for y in range(0, 480, 5))
    t = Terminal(vt640=True)
    # GS, move (0,0), line to (1023,0): the bottom screen row; CAN; text
    t.feed(b"\x1d\x20\x60\x20\x40\x20\x60\x3f\x5f\x18AB")
    px = t.render()
    assert all(px[479 * 640 + x] for x in range(640))
    assert sum(px[479 * 640:]) == 640 and t.gmode is None
    t.feed(b"\x1d\x1b/2d\x20\x60\x20\x40\x20\x60\x3f\x5f")   # XOR the same line away
    assert sum(t.g) == 0
    t.feed(b"\x1b\x0c\x1c\x30\x60\x28\x40")                 # clear; a point
    assert sum(t.g) == 1


def test_syn53_vt640_mouse():
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        print("  skip test_syn53_vt640_mouse (SYNCLAVIER_W0 not set)")
        return
    from sim.boot import boot_from_w0
    cpu, _ = boot_from_w0(image, disk_mb=30, terminal="vt640", mouse=True)

    def run_for(sec):
        end = cpu.time_ns + int(sec * 1e9)
        while cpu.time_ns < end and not cpu.halted:
            cpu.run(20_000)

    def until(pred, limit):
        n = 0
        while n < limit and not cpu.halted and not pred():
            n += cpu.run(100_000)
    until(lambda: b"Ready >" in bytes(cpu.terminal.out), 30_000_000)
    for cmd in (b"create user\r", b"set rtp syn-5.3\r", b"play\r"):   # as sim.lockstep.syn53_cpu
        k = bytes(cpu.terminal.out).count(b"Ready >")
        cpu.terminal.feed(cmd)
        if cmd != b"play\r":
            until(lambda: bytes(cpu.terminal.out).count(b"Ready >") > k, 10_000_000)
    run_for(8)
    assert cpu.halted is None, cpu.halted
    m = cpu.mouse
    assert bytes(m.commands[:3]) == b"\x00Ds", m.commands[:3]
    n = len(m.commands)
    run_for(0.2)
    assert m.commands[n:].count(0o120) >= 8                 # P every 20 ms


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
