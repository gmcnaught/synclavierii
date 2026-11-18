#!/usr/bin/env python3
"""tools/demo.py: demo script parsing, the events it compiles to (the MIDI
hdl/core/midi_vpk.sv takes, the keys hdl/core/ps2_ascii.sv sends), the
board player's event list and the simulator's input mapping. Standard
library only; no disk images.

Run:  python3 tests/test_demo.py
"""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from tools import demo  # noqa: E402
from sim.devices.synth import vpk_button_number  # noqa: E402

PIECE = """title: Two notes
beat: 500
part: Right | key=C | clef=G
0 1 C4 80
1 1 E4
"""


def compile_(text, files=None):
    with tempfile.TemporaryDirectory() as d:
        for name, body in (files or {}).items():
            with open(os.path.join(d, name), "w") as f:
                f.write(body)
        path = os.path.join(d, "t.demo")
        with open(path, "w") as f:
            f.write(text)
        return demo.parse(path)


def test_steps():
    s = compile_("""title: T   # a comment
w1: W1-TIMBRES.IMG
type D  # trailing comment and spaces
key ENTER F3
wait 1
record
button seqb
press trrout
release trrout
program 9
note C4 0.5 90
play p.txt tempo=60
end
wait 3
""", {"p.txt": PIECE})
    assert s.title == "T" and s.header["w1"] == "W1-TIMBRES.IMG"
    ev = [(round(t, 3), k, d) for t, k, d in s.events]
    seqb = vpk_button_number("seqb")
    rout = vpk_button_number("trrout")
    assert ev[:3] == [(0.0, "term", b"D"), (0.1, "term", "ENTER"), (0.2, "term", "F3")]
    assert s.record == 1.3
    assert ev[3:5] == [(1.3, "midi", bytes((0x9F, seqb, 64))), (1.4, "midi", bytes((0x8F, seqb, 0)))]
    assert ev[5:7] == [(1.7, "midi", bytes((0x9F, rout, 64))), (1.7, "midi", bytes((0x8F, rout, 0)))]
    assert ev[7] == (1.7, "midi", bytes((0xC0, 9)))
    t = 1.7 + 2.7                              # program: four taps, 1.5 s for the bank
    assert ev[8:10] == [(round(t, 3), "midi", bytes((0x90, 60, 90))), (round(t + 0.5, 3), "midi", bytes((0x80, 60, 0)))]
    t += 0.5                                   # play at 60 BPM: 1 s beats
    assert ev[10:] == [(round(t, 3), "midi", bytes((0x90, 60, 80))), (round(t + 0.98, 3), "midi", bytes((0x80, 60, 0))),
                       (round(t + 1, 3), "midi", bytes((0x90, 64, 100))), (round(t + 1.98, 3), "midi", bytes((0x80, 64, 0)))]
    assert round(s.end, 3) == round(t + 1.98 + 0.5, 3)


def test_button_channels():
    assert demo.button_msg(100, True) == bytes((0x9F, 100, 64))
    assert demo.button_msg(130, False) == bytes((0x8E, 2, 0))       # PBN 128-159: channel 15


def test_play_options():
    files = {"p.txt": PIECE}
    s = compile_("play p.txt transpose=-24 velocity=50 from=1\n", files)
    assert [e[2] for e in s.events] == [bytes((0x90, 40, 50)), bytes((0x80, 40, 0))]
    s = compile_("play p.txt parts=1 to=1\n", files)
    assert [e[2][1] for e in s.events] == [60, 60]
    # a key struck again while held is lifted first
    s = compile_("play q.txt\n", {"q.txt": "part: A\n0 2 C4\n1 2 C4\n"})
    assert [(round(t, 2), d[0], d[1]) for t, _, d in s.events] == [
        (0.0, 0x90, 60), (0.5, 0x80, 60), (0.5, 0x90, 60), (1.48, 0x80, 60)]


def test_errors():
    for text in ("button nosuch\n", "key HOME\n", "frobnicate 1\n", "program 200\n", "wait\n"):
        try:
            compile_(text)
        except ValueError as e:
            assert "t.demo:1:" in str(e)
        else:
            raise AssertionError(text)


def test_board_events():
    s = compile_("type A:\nkey ENTER\nnote A4 0.1\ntype x\nwait 1\ntype y\n")
    assert [(round(t, 3), k, d) for t, k, d in demo.board_events(s)] == [
        (0.0, "keys", ["text:A", "text::", "ENTER"]),
        (0.3, "midi", [0x90, 69, 100]), (0.4, "midi", [0x80, 69, 0]),
        (0.4, "keys", ["text:x"]), (1.5, "keys", ["text:y"])]


class FakeKeyboard:
    def __init__(self):
        self.log = []

    def press_button(self, pbn, down=True):
        self.log.append(("button", pbn, down))

    def press_key(self, key, down=True, velocity=100):
        self.log.append(("key", key, down, velocity))


class FakeTerminal:
    def __init__(self):
        self.fed = b""

    def feed(self, data):
        self.fed += data


class FakeCpu:
    def __init__(self):
        self.keyboard, self.terminal, self.time_ns = FakeKeyboard(), FakeTerminal(), 0


def test_sim_input():
    cpu = FakeCpu()
    inp = demo.SimInput(cpu)
    inp.apply("term", "F3")
    inp.apply("term", b"x")
    assert cpu.terminal.fed == b"\x1bORx"
    inp.apply("midi", bytes((0x90, 60, 77)))
    inp.apply("midi", bytes((0x80, 60, 0)))
    inp.apply("midi", bytes((0x9E, 2, 64)))
    assert cpu.keyboard.log == [("key", 36, True, 77), ("key", 36, False, 64), ("button", 130, True)]
    cpu.keyboard.log = []
    inp.apply("midi", bytes((0xC0, 9)))       # bank 2, entry 2
    times = []
    while inp.next_ns() is not None:
        cpu.time_ns = inp.next_ns()
        times.append(cpu.time_ns)
        inp.due(cpu.time_ns)
    names = [vpk_button_number(n) for n in ("bankb", "timb.1", "entryb", "timb.1")]
    assert [e[1] for e in cpu.keyboard.log] == [b for b in names for _ in (0, 1)]
    assert [e[2] for e in cpu.keyboard.log] == [True, False] * 4
    assert times == [0, 100_000_000, 300_000_000, 400_000_000, 1_900_000_000, 2_000_000_000,
                     2_200_000_000, 2_300_000_000]


def test_frame_planes():
    px = bytes([0, 1, 1, 0])
    assert demo.frame_planes(px) == bytes([0, 0xFF, 0xFF, 0, 0, 0x66, 0x66, 0, 0, 0x33, 0x33, 0])


def test_fm_chunks_equal_one_render():
    """Chunked rendering (fm_render_parallel, whole-chunk cuts) gives the
    frames of one sim/pcm.py render_frames() call (pcm_out.sv), across chunk
    boundaries and writes inside chunks."""
    import math
    from sim.pcm import render_frames
    log, t = [], 1_000
    def w(ch, fn, v):
        nonlocal t
        log.append((t, ch, fn, v))
        t += 1_000
    w(1, 4, 0)                                   # carrier TIM: wave memory 0
    w(1, 6, 0)                                   # ZMA
    for i in range(256):
        w(1, 7, round(127.5 + 120 * math.sin(2 * math.pi * i / 256)))
    for ch, (inc, nnu, onu) in ((0, (85, 159, 1)), (1, (126, 192, 1))):
        w(ch, 0, inc); w(ch, 1, nnu); w(ch, 2, onu)
    w(0, 0o13, 128)                              # ISHC: pan centre, shift 0
    w(0, 0o10, 250); w(0, 0o11, 40); w(0, 0o12, 90)       # index envelope
    w(1, 0o13, 255)                              # VOL
    w(1, 0o10, 240); w(1, 0o11, 200); w(1, 0o12, 255)     # volume envelope
    log.append((23_000_000, 1, 0o12, 0))         # release inside a chunk
    old = demo.CHUNK_NS
    demo.CHUNK_NS = 10_000_000
    try:
        start, end = 2_000_000, 47_000_000
        got = demo.fm_render_parallel(log, start, end, 1, jobs=1)
        assert got == render_frames(log, start, end, voices=1) and len(got) == 2160
        assert max(abs(l) for l, _ in got) > 100
    finally:
        demo.CHUNK_NS = old


def test_write_mix():
    import struct
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "m.wav")
        fm = [(2048, -2048), (32767, 0)]         # one voice at full level (1/16); pcm_out.sv clipped
        n = demo.write_mix(path, fm, [(100, -100), (-1000, 0)], 3)
        data = open(path, "rb").read()[44:]
        assert struct.unpack("<6h", data) == (2148, -2148, 31767, 0, 0, 0) and n == 1
        n = demo.write_mix(path, fm, [(31000, 0)], 2)    # FM + poly over full scale: clipped again
        assert struct.unpack("<4h", open(path, "rb").read()[44:]) == (32767, -2048, 32767, 0) and n == 2
        n = demo.write_mix(path, fm, [], 2, gain=0.5)
        assert struct.unpack("<4h", open(path, "rb").read()[44:]) == (1024, -1024, 16384, 0) and n == 1


def test_baud():
    s = compile_("baud: 38400\nwait 1\n")
    assert demo.script_baud(s) == 38400 and demo.script_baud(s, 19200) == 19200
    assert demo.script_baud(compile_("wait 1\n")) == 9600
    try:
        demo.script_baud(compile_("baud: 12345\n"))
    except ValueError:
        pass
    else:
        raise AssertionError("bad baud accepted")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
