#!/usr/bin/env python3
"""The SMPTE reader from MIDI Time Code (sim/devices/smpte.py, D70
subsystem 8 on the MIDI card's bus) and, with SYNCLAVIER_W0 set, SYN-5.3's
sequencer chasing MTC through it.

Run:  python3 tests/sim/test_smpte.py
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from sim.devices.midi import MidiSubsystem  # noqa: E402
from sim.devices.smpte import (LIMIT_NS, SmpteReader, full_frame, next_frame,  # noqa: E402
                               quarter_frame_ns, quarter_frames)

PLAY_TIME_LSB = 0o53712     # SYN-5.3's sequencer play time, ms (found by behaviour)
ZERO_TIME = 50              # GLOBLITS: PLAY.TIME.LSB of sequence time 0.000


def feed(r, msgs, period):
    for msg in msgs:
        for b in msg:
            r.receive(b)
        for _ in range(period // 1000):
            r.tick(1000)


def scan(r):
    """SMPTE.SCAN's reads: D70, D71, D72, D73 (the last latches)."""
    return [r.read(d) for d in (0o70, 0o71, 0o72, 0o73)]


def test_next_frame():
    assert next_frame((0, 0, 0, 23), 0) == (0, 0, 1, 0)
    assert next_frame((0, 0, 0, 24), 1) == (0, 0, 1, 0)
    assert next_frame((0, 0, 59, 29), 2) == (0, 1, 0, 2)      # drop frame
    assert next_frame((0, 9, 59, 29), 2) == (0, 10, 0, 0)     # not on minute 10
    assert next_frame((0, 0, 59, 29), 3) == (0, 1, 0, 0)
    assert next_frame((23, 59, 59, 29), 3) == (0, 0, 0, 0)


def test_quarter_frames_to_readings():
    """Eight pieces give the time; a reading is the one latched by the
    previous D73 read, with the frame before the one the bit counts in."""
    r = SmpteReader()
    assert scan(r) == [0o410, 0o100000, 0, 0]                 # power on: no sync
    p = quarter_frame_ns(3)
    feed(r, quarter_frames((1, 2, 3, 4), 3, 7), p)
    assert scan(r)[1] & 0o100000                              # 7 pieces: not yet
    feed(r, quarter_frames((1, 2, 3, 4), 3, 8)[7:], 0)        # piece 7
    r.latch()
    # T0 + 1.75 frames: frame 5, quarter 3; the last complete frame is 4
    assert r.info == (60, 3 << 8 | 4, 1 << 8 | 2), r.info
    for _ in range(p // 2000):                                # half a quarter frame
        r.tick(1000)
    r.latch()
    assert r.info[0] == 60 + 9 and r.info[1] == 3 << 8 | 4    # 20 * 0.5 -> 9 (floor of 9.99)
    msgs = quarter_frames((1, 2, 3, 4), 3, 16)
    feed(r, msgs[8:9], 0)                                     # piece 0: frame 6, quarter 0
    v = scan(r)                                               # (the latch from before)
    assert v[1] == 60 + 9, v
    v = scan(r)
    assert v[1:] == [0, 3 << 8 | 5, 1 << 8 | 2], v


def test_drop_frame_and_rates():
    """80 quarter frames over a minute boundary at each rate: the reading
    is 18 frames on (frame 19 being read), status "004" only for drop frame."""
    for rate, df in ((0, 0), (1, 0), (2, 0o4), (3, 0)):
        r = SmpteReader()
        feed(r, quarter_frames((0, 0, 59, 20), rate, 80), quarter_frame_ns(rate))
        r.latch()
        want = (0, 0, 59, 20)
        for _ in range(18):
            want = next_frame(want, rate)
        assert r.info == (df << 8 | 60 + 19, want[2] << 8 | want[3], want[1]), (rate, r.info, want)
    assert want == (0, 1, 0, 8 if rate == 3 else 0)


def test_position_matches_sender():
    """At every quarter frame the reader's position (last frame + 1, bit)
    is the sender's: piece n of the eight from frame T0 is sent at T0 + n/4."""
    for rate in range(4):
        r = SmpteReader()
        t0 = (0, 0, 59, 10)
        for i, msg in enumerate(quarter_frames(t0, rate, 400)):
            for b in msg:
                r.receive(b)
            if i >= 7:
                want = t0
                for _ in range(i // 4):
                    want = next_frame(want, rate)
                assert r.cur == want and r.quarter == i % 4 and r.valid, (rate, i, r.cur, want)


def test_invalid_cases():
    p = quarter_frame_ns(1)
    r = SmpteReader()
    feed(r, quarter_frames((0, 0, 1, 0), 1, 16), p)
    r.latch()
    assert r.info[0] < 0o100000
    for _ in range(LIMIT_NS // 1000):                         # stopped: time-out
        r.tick(1000)
    r.latch()
    assert r.info[0] & 0o100000
    for b in full_frame((0, 10, 0, 0), 1):                    # located: shown, not valid
        r.receive(b)
    r.latch()
    assert r.info[0] & 0o100000 and r.info[1:] == (0, 10), r.info
    msgs = quarter_frames((0, 10, 0, 0), 1, 24)
    feed(r, msgs[:12], p)
    r.latch()
    assert r.info[0] < 0o100000 and r.info[1] == 1 and r.info[2] == 10, r.info
    feed(r, [msgs[14]], p)                                    # a piece skipped
    r.latch()
    assert r.info[0] & 0o100000
    feed(r, msgs[16:24], p)                                   # eight in order again
    r.latch()
    assert r.info[0] < 0o100000
    r = SmpteReader()                                         # real time inside, other SysEx
    for msg in quarter_frames((0, 0, 1, 0), 1, 8):
        for b in (msg[0], 0xF8, msg[1], 0xF0, 0x43, 0x10, 0x01, 0x01, 0, 0, 0, 0, 0xF7):
            r.receive(b)
    r.latch()
    assert r.info[0] == 60 and r.info[1] == 1 << 8 | 0, r.info


def test_card_routing():
    """Select 8 reaches the reader only when it is installed; the MIDI
    card keeps its FIFO and still latches MCHA on D71 writes."""
    c = MidiSubsystem()
    c.write(0o70, 8)
    assert c.read(0o70) == 0
    r = SmpteReader()
    c = MidiSubsystem(smpte=r)
    c.receive(0x90)
    c.write(0o70, 8)
    assert c.read(0o70) == 0o410 and c.read(0o71) == 0o100000
    c.write(0o71, 0o224)
    assert c.mcha == 0o224 & 0xF and r.opcode == 0o224
    c.write(0o70, 16)
    assert c.read(0o70) == 16 and c.read(0o71) == 1
    c.tick(1000)
    assert r.elapsed == LIMIT_NS


def test_syn53_chases_mtc():
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        print("  skip test_syn53_chases_mtc (SYNCLAVIER_W0 not set)")
        return
    print("  " + chase(image))


def chase(image, start=(0, 0, 5, 0), seconds=2.5):
    """Boot SYN-5.3 with the velocity keyboard and the MIDI card with the
    reader; MIDI IN sync on (hold MIDI, press EXT twice) and MTC into the
    card's FIFO: the sequencer stays at 0 (SYN-5.3 ignores F1); then
    SMPTE on (hold SMPTE, press EXT) and 29.97 drop-frame MTC (the default
    SMPTE mode, Drop Frame) from `start`. Returns the numbers."""
    from sim.boot import boot_from_w0
    from sim.devices.synth import vpk_button_number as B
    r = SmpteReader()
    card = MidiSubsystem(smpte=r)
    cpu, _ = boot_from_w0(image, keyboard="vpk", midi=card)
    kb = cpu.keyboard

    def run_to(t):
        while cpu.time_ns < t and not cpu.halted:
            cpu.run(2000)
    ms = 1_000_000
    run_to(10_600 * ms)
    for t, name, down in ((10_600, "midi", 1), (10_700, "ext", 1), (10_800, "ext", 0),
                          (10_900, "ext", 1), (11_000, "ext", 0), (11_100, "midi", 0)):
        run_to(t * ms)
        kb.press_button(B(name), bool(down))
    run_to(11_200 * ms)
    assert kb.display_text()[1].startswith("MIDI IN Sync"), kb.display_text()   # EXT.CLOCK.MODE 3
    p = quarter_frame_ns(2)
    for msg in quarter_frames(start, 2, 4 * 15):            # 0.5 s, through the card
        for b in msg:
            card.receive(b)
        run_to(cpu.time_ns + p)
    assert cpu.mem[PLAY_TIME_LSB] == 0, cpu.mem[PLAY_TIME_LSB]
    assert not card.fifo
    t = cpu.time_ns + 200 * ms
    for name, down in (("smpte", 1), ("ext", 1), ("ext", 0), ("smpte", 0)):
        run_to(t)
        kb.press_button(B(name), bool(down))
        t += 100 * ms
    run_to(t)
    assert kb.display_text()[1].startswith("Drop Frame SMPTE"), kb.display_text()
    msgs = quarter_frames(start, 2, int(seconds * 120))
    rows, t = [], cpu.time_ns
    for i, msg in enumerate(msgs):
        for b in msg:
            r.receive(b)
        t += p
        run_to(t)
        if i % 60 == 59:                                    # every 0.5 s
            # the sender's position now (i + 1 quarters after T0): 80 bits a
            # frame at 2.3976 bits/ms (SYN-5.3's BITS.PER.MSEC, mode 0)
            want = (start[2] * 30 + (i + 1) / 4) * 80 * 1250 / 2997
            rows.append((i + 1, round(want), cpu.mem[PLAY_TIME_LSB] - ZERO_TIME))
    assert cpu.halted is None, cpu.halted
    first = next(k for k, row in enumerate(rows) if row[2] > 0)
    assert first <= 1, rows                                 # locked within 1 s
    for q, want, got in rows[first + 1:]:
        assert abs(got - want) <= 10, rows
    return "MTC quarter frames, ms wanted, sequence ms: " + ", ".join("%d %d %d" % x for x in rows)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
