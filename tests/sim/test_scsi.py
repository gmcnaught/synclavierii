#!/usr/bin/env python3
"""D24 SCSI host and disk target (sim/devices/scsi.py), and the Release 5.3
W0 boot when SYNCLAVIER_W0 names a W0 image (Synclavier3's
"W0 Disk Image.simg").

Run:  python3 tests/sim/test_scsi.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.devices.scsi import (  # noqa: E402
    ACK, ATN, BSY, CD, IO, MSG, REQ, SEL, ScsiDisk, ScsiHost)


def connect(h, target=5):
    """Arbitrate, select with ATN, IDENTIFY, as LOADER:SCSILOAD does."""
    h.write(0o24, 0o10400)                    # select D24 board 0
    assert h.read(0o24) & 0o7400 == 0o400
    h.write(0o24, 0)
    assert h.read(0o25) & (BSY | SEL) == 0    # bus free
    h.write(0o25, BSY)
    h.write(0o24, 0o100)                      # ID 6
    assert h.read(0o24) & 0o200 == 0          # ID 7 not on the bus: won
    h.write(0o25, BSY | SEL)
    h.write(0o24, 0o100 | (1 << target))
    h.write(0o25, BSY | SEL | ATN)
    h.write(0o25, SEL | ATN)                  # release BSY
    assert h.read(0o25) & BSY                 # target selected
    h.write(0o24, 0)
    h.write(0o25, ATN)                        # release SEL
    assert h.read(0o25) & (REQ | MSG | CD) == REQ | MSG | CD
    h.write(0o25, 0)                          # release ATN
    h.write(0o26, 0o200)                      # IDENTIFY, LUN 0
    assert h.read(0o25) & (REQ | CD | IO | MSG) == REQ | CD


def test_extended_read_with_manual_last_byte():
    data = bytes(range(256)) * 8                          # 4 blocks
    h = ScsiHost({5: ScsiDisk(data)})
    connect(h)
    for b in (0x28, 0):                                   # EXTENDED READ, LUN 0
        h.write(0o26, b)
    h.write(0o27, 0)                                      # LBA 1
    h.write(0o27, 1)
    h.write(0o26, 0)
    h.write(0o27, 2)                                      # 2 blocks
    h.write(0o26, 0)                                      # control
    assert h.read(0o25) & (REQ | IO | CD) == REQ | IO     # data in
    words = [h.read(0o27) for _ in range(511)]
    assert words[0] == 0x0001 and words[127] == 0xFEFF
    last_hi = h.read(0o26)
    last_lo = h.read(0o24) & 0o377                        # MONITOR 5.3: peek, then ACK
    h.write(0o25, ACK)
    assert not h.read(0o25) & REQ
    h.write(0o25, 0)
    assert (last_hi, last_lo) == (0xFE, 0xFF)
    assert h.read(0o25) & (REQ | CD | IO) == REQ | CD | IO   # status
    assert h.read(0o27) == 0x0000                         # GOOD, COMMAND COMPLETE
    assert h.read(0o25) & (BSY | REQ) == 0                # bus free
    assert h.log == [(5, bytes([0x28, 0, 0, 0, 0, 1, 0, 0, 2, 0]))]


def read10(h, lba, n):
    """Connect and send EXTENDED READ (lba, n blocks); the data phase follows."""
    connect(h)
    for b in (0x28, 0, 0, 0, lba >> 8, lba & 0xFF, 0, 0, n, 0):
        h.write(0o26, b)


def drain(h, n):
    """Read n blocks as words (taking each block as soon as REQ is up),
    then status and message. Returns the simulated time spent."""
    t = h.time_ns
    for _ in range(n):
        while not h.read(0o25) & REQ:                    # disk time: poll REQ
            h.tick(100_000)
        for _ in range(256):
            h.read(0o27)
    assert h.read(0o27) == 0x0000                        # status, message
    return h.time_ns - t


def test_disk_time_seek():
    """Disk time with seek time: a READ that continues the last one costs
    n x block_ns; one that does not (or the first) costs seek_ns more."""
    h = ScsiHost({5: ScsiDisk(bytes(512 * 8))}, block_ns=500_000, seek_ns=20_000_000)
    read10(h, 0, 2)
    assert drain(h, 2) == 21_000_000                     # first READ: seek + 2 blocks
    read10(h, 2, 2)
    assert drain(h, 2) == 1_000_000                      # continues: 2 blocks
    read10(h, 1, 1)
    assert drain(h, 1) == 20_500_000                     # back one: seek + 1 block
    h.head = None                                        # as after a state image load
    read10(h, 2, 1)
    assert drain(h, 1) == 20_500_000


def test_write_and_bad_command():
    disk = ScsiDisk(bytes(1024))
    h = ScsiHost({5: disk})
    connect(h)
    for b in (0x0A, 0, 0, 1, 1, 0):                       # WRITE(6) block 1
        h.write(0o26, b)
    assert h.read(0o25) & (REQ | IO | CD) == REQ          # data out
    for i in range(256):
        h.write(0o27, 0x1234 + i)
    assert h.read(0o27) >> 8 == 0                         # GOOD
    assert disk.data[512:514] == b"\x12\x34" and disk.writes == 1
    connect(h)
    for b in (0x02, 0, 0, 0, 0, 0):                       # unsupported (group 0)
        h.write(0o26, b)
    assert h.read(0o27) >> 8 == 0x02                      # CHECK CONDITION
    connect(h)
    for b in (0x03, 0, 0, 0, 18, 0):                      # REQUEST SENSE
        h.write(0o26, b)
    sense = bytes(h.read(0o26) for _ in range(18))
    assert sense[0] == 0x70 and sense[2] == 0x05          # ILLEGAL REQUEST
    assert h.read(0o27) == 0


def test_release_5_3_monitor_boots_from_w0():
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        print("  skip test_release_5_3_monitor_boots_from_w0 (SYNCLAVIER_W0 not set)")
        return
    from sim.boot import boot_from_w0
    cpu, lay = boot_from_w0(image)
    for _ in range(40):
        cpu.run(500_000)
        if cpu.halted or b"Ready >" in bytes(cpu.terminal.out):
            break
    text = bytes(b & 0o177 for b in cpu.terminal.out).decode("latin-1")
    assert cpu.halted is None, (cpu.halted, text)
    assert "Synclavier System Monitor - 2021/03/09" in text and "Ready >" in text, text
    cmds = {c[0] for _, c in cpu.scsi.log}
    assert {0x12, 0x00, 0x25, 0x28} <= cmds, cmds


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
