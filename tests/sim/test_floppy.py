#!/usr/bin/env python3
"""Tests for the D100 floppy controller (sim/devices/floppy.py), stdlib only.

The programs drive the controller the way NED's FLPLOAD and RTP DISKREAD
do: restore, load the track register, seek through D103, set and verify
the sector register, issue read (210), and assemble words from byte pairs
with BSOR while polling DRQ.

Run:  python3 tests/sim/test_floppy.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.asm import assemble  # noqa: E402
from sim.cpu import HALT_NO_SYN_WRITE  # noqa: E402
from sim.devices.floppy import (  # noqa: E402
    BUSY, INDEX, NOT_READY, PROTECT, RNF, TRACK0, FloppyController, Media)
from sim.system import make_system  # noqa: E402

SPT = 5


def media(sectors=20, protected=False):
    # word i of logical sector n = n * 1000 (octal) + i
    words = [(n << 9) + i for n in range(sectors) for i in range(256)]
    return Media(words, sectors_per_track=SPT, protected=protected)


def system(src, m=None):
    cpu = make_system(floppy=True)
    if m is not None:
        cpu.floppy.insert(0, m)
    words, labels = assemble(src, 0o1000)
    cpu.load(words, 0o1000)
    cpu.r[0o17] = 0o1000
    cpu.labels = labels
    return cpu


def run_to(cpu, label, limit=5_000_000):
    target = cpu.labels[label]
    n = 0
    while cpu.pc != target and n < limit:
        assert cpu.step(), cpu.halted
        n += 1
    assert cpu.pc == target, "did not reach %s" % label


# R13 = track, R0 = sector (1-based), R1 = buffer, R2 = words; result in R3
READ_SECTOR = """
        IM(0) TO D104       ; drive 0, side 0
        IM(1) TO D100       ; restore, rate 1
WREST:  D100 TO R3
        IM(1) TO TAND3
        RE(WREST) TO RTNZ
        R13 TO D103         ; seek target
        IM(21) TO D100      ; seek, rate 1
WSEEK:  D100 TO R3
        IM(1) TO TAND3
        RE(WSEEK) TO RTNZ
        R0 TO D102
        D102 TO TSUB0       ; verify the sector register
        PCI TO D100
        DATA 210            ; read sector, IBM format
N:      D100 TO R3
        IM(2) TO TAND3
        RE(NODRQ) TO RTZE
        D103 TO R12         ; first byte
W2:     D100 TO R3
        IM(2) TO TAND3
        RE(W2) TO RTZE
        D103 TO R3          ; second byte
        R12 TO BSOR3        ; first byte low, second high
        R3 TO MR1I
        IM(1) TO SUB2
        RE(N) TO RTNZ
        RE(DONE) TO RTRA
NODRQ:  IM(1) TO TAND3      ; still busy?
        RE(N) TO RTNZ
DONE:   D100 TO R3          ; final status
        D101 TO R4          ; track register
END:    RE(END) TO RTRA
"""


def test_media_mapping():
    m = Media([0] * 404 * 256, sectors_per_track=5)
    assert m.sectors == 404
    assert m.logical(0, 0, 1) == 0 and m.logical(1, 0, 1) == 5
    assert m.logical(80, 0, 4) == 403 and m.logical(80, 0, 5) is None
    assert m.logical(0, 1, 1) is None and m.logical(0, 0, 6) is None
    ds = Media([0] * 40 * 256, sectors_per_track=5, sides=2)
    assert ds.logical(1, 1, 2) == 16   # (cyl 1 * 2 + side 1) * 5 + 1


def test_restore_seek_read_sector():
    cpu = system(READ_SECTOR, media())
    cpu.r[0o13] = 2          # track 2
    cpu.r[0] = 3             # sector 3 -> logical 2 * 5 + 2 = 12
    cpu.r[1] = 0o4000
    cpu.r[2] = 256
    run_to(cpu, "END")
    assert cpu.mem[0o4000:0o4000 + 256] == [(12 << 9) + i for i in range(256)]
    assert cpu.r[3] & (BUSY | RNF) == 0 and cpu.r[4] == 2
    assert cpu.floppy.head[0] == 2
    cmds = [c for c, *_ in cpu.floppy.commands]
    assert cmds == [0o1, 0o21, 0o210]
    # the seek took two steps at 6 ms
    assert cpu.time_ns > 12_000_000


def test_record_not_found():
    cpu = system(READ_SECTOR, media(sectors=10))
    cpu.r[0o13] = 3          # beyond the 10-sector media (2 tracks)
    cpu.r[0] = 1
    cpu.r[1] = 0o4000
    cpu.r[2] = 256
    run_to(cpu, "END")
    assert cpu.r[3] & RNF and not cpu.r[3] & BUSY


def test_track_register_mismatch_is_rnf():
    fc = FloppyController()
    fc.insert(0, media())
    fc.head[0] = 1           # head on cylinder 1, track register says 0
    fc.write(0o102, 1)
    fc.write(0o100, 0o210)
    fc.tick(100_000)
    assert fc.read(0o100) & RNF


def test_write_sector_and_protect():
    m = media()
    fc = FloppyController()
    fc.insert(0, m)
    fc.write(0o102, 2)       # track 0, sector 2 -> logical 1
    fc.write(0o100, 0o250)   # write sector
    fc.tick(100_000)
    for i in range(256):
        assert fc.read(0o100) & 2       # DRQ
        fc.write(0o103, i & 0o377)      # low byte
        fc.write(0o103, 0o200)          # high byte
    assert not fc.read(0o100) & BUSY
    assert m.words[256:512] == [(0o200 << 8) | (i & 0o377) for i in range(256)]
    fc.insert(1, media(protected=True))
    fc.write(0o104, 1)
    fc.write(0o100, 0o250)
    assert fc.read(0o100) & PROTECT and not fc.read(0o100) & BUSY


def test_index_pulse_ready_and_force_interrupt():
    fc = FloppyController()
    assert fc.read(0o100) & NOT_READY            # no media in drive 0
    fc.insert(0, media())
    fc.write(0o100, 0o320)                       # force interrupt: Type I status
    seen = set()
    for _ in range(400):                         # 400 ms, > 2 revolutions
        fc.tick(1_000_000)
        seen.add(bool(fc.read(0o100) & INDEX))
    assert seen == {True, False}
    assert fc.read(0o100) & TRACK0
    fc.write(0o103, 40)
    fc.write(0o100, 0o23)                        # seek 40 tracks at 20 ms
    assert fc.read(0o100) & BUSY
    fc.write(0o100, 0o320)                       # abort
    assert not fc.read(0o100) & BUSY


def test_unmodelled_command_halts():
    cpu = system("""
        PCI TO D100
        DATA 304            ; read address: not modelled
    """, media())
    assert not cpu.step()
    assert cpu.halted.reason == HALT_NO_SYN_WRITE and cpu.halted.device == 0o100


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
