#!/usr/bin/env python3
"""The MIDI subsystem card model (sim/devices/midi.py, D70-D73) and, with
SYNCLAVIER_W0 set, SYN-5.3 detecting it and reading MIDI through it.

Run:  python3 tests/sim/test_midi.py
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from sim.devices.midi import MidiSubsystem  # noqa: E402
from sim.devices.terminal import D70_EXISTS  # noqa: E402
from sim.system import make_system  # noqa: E402


def test_detection_sequence():
    """INIT.MIDI.SUBSYSTEMS (142-MIDI:506-531): select 16 reads back, MSTA
    bit 1 clear (cables OK); select 17 reads 0 (one card)."""
    c = MidiSubsystem()
    c.write(0o70, 16)
    assert c.read(0o70) == 16 and c.read(0o71) & 2 == 0
    for j in range(8, 13):
        c.write(0o71, j)
        c.write(0o72, c.read(0o72))
    c.write(0o71, 0)
    c.write(0o70, 17)
    assert c.read(0o70) == 0 and c.read(0o71) == 0
    for sel in (8, 32):                        # no SMPTE reader, no DSP70
        c.write(0o70, sel)
        assert c.read(0o70) == 0
    assert c.out == []


def test_input_fifo():
    c = MidiSubsystem()
    c.write(0o70, 16)
    assert c.read(0o71) == 0
    for b in (0x90, 60, 100):
        c.receive(b)
    assert c.read(0o71) == 1
    c.write(0o71, 4)
    assert [c.read(0o72) for _ in range(4)] == [0x90, 60, 100, 0]
    assert c.read(0o71) == 0
    for b in range(70):                        # 64 bytes, then dropped
        c.receive(b)
    assert len(c.fifo) == 64 and c.dropped == 6
    c.write(0o70, 17)
    assert c.read(0o71) == 0 and c.read(0o72) == 0 and len(c.fifo) == 64
    c.write(0o70, 16)
    c.write(0o71, 12)                          # port 4 with reset: flush
    assert c.read(0o72) == 0 and not c.fifo


def test_output_ports():
    seen = []
    c = MidiSubsystem(output=seen.append)
    c.write(0o70, 16)
    for port in range(4):
        c.write(0o71, port)
        c.write(0o72, 0xB0 | port)
    c.write(0o71, 4)
    c.write(0o72, 0x55)                        # the input port: no output
    c.write(0o71, 8)
    c.write(0o72, 0x66)                        # reset: dropped
    c.write(0o70, 17)
    c.write(0o71, 0)
    c.write(0o72, 0x77)                        # another subsystem: dropped
    assert c.out == [(p, 0xB0 | p) for p in range(4)] and seen == [0xB0, 0xB1, 0xB2, 0xB3]


def test_system_bit():
    cpu = make_system(midi=MidiSubsystem())
    assert cpu.terminal.device_bits & D70_EXISTS and cpu.midi is not None
    assert not make_system().terminal.device_bits & D70_EXISTS


def test_syn53_detects_card_and_reads_midi():
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        print("  skip test_syn53_detects_card_and_reads_midi (SYNCLAVIER_W0 not set)")
        return
    from sim.boot import boot_from_w0
    card = MidiSubsystem()
    log = []
    read, write = card.read, card.write
    card.read = lambda d: log.append(("R", d, card.sel)) or read(d)
    card.write = lambda d, v: log.append(("W", d, v)) or write(d, v)
    cpu, _ = boot_from_w0(image, disk_mb=30, midi=card)

    def run_for(sec):
        end = cpu.time_ns + int(sec * 1e9)
        while cpu.time_ns < end and not cpu.halted:
            cpu.run(20_000)
    run_for(11)
    assert cpu.halted is None, cpu.halted
    # CREATE USER has not been run on a raw image, so SYN-5.3 may not reach
    # its menu; the card is probed in its start-up either way
    assert log[:3] == [("W", 0o70, 16), ("R", 0o70, 16), ("R", 0o71, 16)], log[:3]
    assert ("W", 0o70, 17) in log
    polls = sum(1 for e in log if e == ("R", 0o71, 16))
    assert polls > 100, polls                  # SCAN.MIDI's 1 ms (or 5 ms) poll
    for b in (0x90, 60, 100, 0x80, 60, 0):
        card.receive(b)
        run_for(0.00032)
    run_for(0.05)
    assert not card.fifo and card.dropped == 0


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
