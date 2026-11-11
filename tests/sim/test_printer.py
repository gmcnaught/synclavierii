#!/usr/bin/env python3
"""The D40/D41 printer port (sim/devices/printer.py), the VT640 read-back
(tools/vt100.py), the page renderer (tools/print_render.py) and, with
SYNCLAVIER_W0 set, SYN-5.3 printing: the Recorder Display's screen dump
(G, h) and the Music Notation Display's hardcopy (VT640, K, H).

Run:  python3 tests/sim/test_printer.py
"""
import os
import struct
import sys
import zlib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from sim.devices.mouse import Mouse  # noqa: E402
from sim.devices.printer import D54, FAST_NS, IRQ_BIT, Printer  # noqa: E402
from tools.print_render import (CELL_H, MARGIN, header, pdf, png, read_capture,  # noqa: E402
                                render)
from tools.vt100 import GH, GW, Terminal, readback_reply  # noqa: E402


def test_registers():
    p = Printer()
    assert p.read(0o41) == 4 and p.read(0o54) == 0 and p.irq_bits() == 0
    p.write(0o40, 0o101)
    assert p.out == b"A" and p.read(0o41) == 0
    p.tick(FAST_NS - 1)
    assert p.read(0o41) == 0
    p.tick(1)
    assert p.read(0o41) == 5 and p.irq_bits() == 0      # transmit interrupt, not enabled
    p.write(0o54, 1)
    assert p.read(0o54) == 1 and p.irq_bits() == IRQ_BIT
    p.write(0o41, 0)                                    # acknowledge
    assert p.read(0o41) == 4 and p.irq_bits() == 0
    p.write(0o41, 0o100000 | 4 << 8)                    # 9600 baud
    p.write(0o40, 0o102)
    p.tick(1_041_666)
    assert p.read(0o41) == 0
    p.tick(1)
    assert p.irq_bits() == IRQ_BIT and p.out == b"AB"


def test_d54_shared_with_mouse():
    m, p = Mouse(), Printer()
    d = D54(p, m)
    d.write(0o54, 5)                                    # D40 and D44 enabled
    p.write(0o40, 0)
    p.tick(FAST_NS)
    assert d.read(0o54) == 1
    m.write(0o44, 0o163)
    m.tick(1_000_000)
    assert d.read(0o54) == 5
    d.write(0o54, 4)
    assert d.read(0o54) == 4 and p.irq_bits() == 0


def test_set_printer():
    from sim.boot import C_CMOPT, C_STYPE, set_printer
    prog = [0o100377, 0o200] + [0] * 0o400
    prog[0o200 + C_CMOPT] = 0o141473
    out = set_printer(prog)
    assert out[0o200 + C_CMOPT] == 0o141473 | 0o20 and out[0o200 + C_STYPE] == 12 << 8
    assert set_printer(prog, "printronix")[0o200 + C_STYPE] == 11 << 8


def read_screen(reply, groups=128):
    """D40SOU read_screen's decoding of a read-back reply: the line's pixels."""
    src = iter(reply)
    vals = []
    while len(vals) < groups:
        c = next(src)
        if c == 36:
            c, n = 0, next(src) & 0o77
        elif c == 37:
            c, n = 0o77, next(src) & 0o77
        elif c == 38:
            c, n = next(src), next(src) & 0o77
        else:
            n = 1
        vals += [c] * n
    assert next(src) == 0o15 and not list(src)          # the trailer, nothing after
    return [v >> (4 - i) & 1 for v in vals for i in range(5)]


def test_readback():
    t = Terminal(vt640=True, reply=lambda d: got.append(d))
    got = []
    # a line along y = 100, a point, a diagonal
    t.feed(b"\x1d\x23\x64\x20\x40\x23\x64\x3f\x5f"          # (0,100)-(639,100) in Tek units
           b"\x1c\x30\x60\x28\x40"
           b"\x1d\x20\x60\x20\x40\x2f\x7f\x2f\x5f")
    for y in range(GH):
        got.clear()
        t.feed(b"\x1b\"0;%d;128c" % y)
        assert len(got) == 1
        assert read_screen(got[0]) == list(t.g[(GH - 1 - y) * GW:(GH - y) * GW]), y
    assert sum(t.g) > 640
    got.clear()
    t.feed(b"\x1b\"0;5;100C")                                # DQ640 form: no reply
    assert got == []


def hardcopy(plane):
    """Python transcription of D40SOU hardcopy (VT640: 640 x 480, 5-pixel
    groups) reading the screen through readback_reply."""
    W, H, n = GW, GH, 5
    groups, swaths = W // n, (H + 6) // 7
    out = bytearray(b"\r\x03")
    for i in range(swaths):
        arr = bytearray(W + 2)
        last = -1
        for j in range(((H - 1) % 7 if i == swaths - 1 else 6) + 1):
            y = H - 1 - 7 * i - j
            for g, px in enumerate(_groups(read_screen(readback_reply(plane, y, groups)))):
                if px:
                    last = max(last, n * g + n)
                for k in range(n):
                    if px >> k & 1:
                        arr[n * g + n - 1 - k] |= 1 << j
        for b in arr[:last + 1]:
            out += b"\x03\x03" if b == 3 else bytes([b])
        out += b"\x03\x0e"
    return bytes(out + b"\x03\x0c\x03\x02\r")


def _groups(px):
    return [sum(px[5 * g + i] << (4 - i) for i in range(5)) for g in range(len(px) // 5)]


def test_hardcopy_renders_the_screen():
    t = Terminal(vt640=True)
    t.feed(b"\x1d\x23\x64\x20\x40\x23\x64\x3f\x5f\x1d\x20\x60\x20\x40\x2f\x7f\x2f\x5f"
           b"\x1d\x30\x60\x28\x40\x1fSCORE\x18")
    t.g[0 * GW + 7] = t.g[1 * GW + 7] = 1                   # top two rows: a byte 3 (ETX, doubled)
    data = hardcopy(t.g)
    assert b"\x03\x03" in data
    page = render(data)[0]
    for y in range(GH):
        for x in range(GW):
            assert page.px[(MARGIN + y) * page.w + MARGIN + x] == t.g[y * GW + x], (x, y)
    assert sum(page.px) == sum(t.g)


def test_text_and_files():
    data = b"\r\n\x14AB\r\nC\x0c\x14X"
    pages = render(data)
    assert len(pages) == 2
    p = pages[0]
    ink = [(i % p.w, i // p.w) for i, v in enumerate(p.px) if v]
    assert min(y for _, y in ink) >= MARGIN + CELL_H and max(x for x, _ in ink) < MARGIN + 16
    blob = png(p)
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", blob[16:24])
    assert (w, h) == (p.w, p.h)
    i = blob.index(b"IDAT")
    n = struct.unpack(">I", blob[i - 4:i])[0]
    assert len(zlib.decompress(blob[i + 4:i + 4 + n])) == h * (1 + (w + 7) // 8)
    doc = pdf(pages)
    assert doc.startswith(b"%PDF-1.4") and doc.count(b"/Type /Page ") == 2 and doc.rstrip().endswith(b"%%EOF")
    cap = header(3).ljust(1024, b"\0")
    cap = cap[:512] + b"xyz" + cap[515:]
    assert read_capture(cap) == b"xyz"


def _syn53(**kw):
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        return None
    from sim.boot import boot_from_w0
    cpu, _ = boot_from_w0(image, printer="prism", **kw)
    return cpu


def _run_for(cpu, sec):
    end = cpu.time_ns + int(sec * 1e9)
    while cpu.time_ns < end and not cpu.halted:
        cpu.run(20_000)


def test_syn53_screen_dump():
    cpu = _syn53()
    if cpu is None:
        print("  skip test_syn53_screen_dump (SYNCLAVIER_W0 not set)")
        return
    _run_for(cpu, 11)                                       # Main Menu
    cpu.terminal.feed(b"Gh")                                # Recorder Display, print it
    _run_for(cpu, 3)
    assert cpu.halted is None, cpu.halted
    out = bytes(cpu.printer.out)
    lines = out.split(b"\r\n\x14")
    assert lines[0] == b"" and len(lines) == 25 and out.endswith(b"\x0c"), (len(lines), out[-20:])
    assert b"MEMORY RECORDER COMPARATIVE TRACK DISPLAY" in lines[1]
    assert all(len(ln) == 80 for ln in lines[1:-1])


def test_syn53_music_notation_hardcopy():
    cpu = _syn53(terminal="vt640", mouse=True)
    if cpu is None:
        print("  skip test_syn53_music_notation_hardcopy (SYNCLAVIER_W0 not set)")
        return
    planes = []
    reply = cpu.screen.reply
    cpu.screen.reply = lambda d: (planes.append(bytes(cpu.screen.g)) if not planes else None, reply(d))
    _run_for(cpu, 11)
    cpu.terminal.feed(b"K")                                 # Music Notation Display
    _run_for(cpu, 3)
    cpu.terminal.feed(b"H")                                 # print the screen
    last = idle = 0
    while idle < 2 and not cpu.halted and cpu.time_ns < 120e9:
        _run_for(cpu, 1)
        idle = idle + 1 if len(cpu.printer.out) == last else 0
        last = len(cpu.printer.out)
    out = bytes(cpu.printer.out)
    assert out.endswith(b"\x03\x0c\x03\x02\r"), out[-10:]
    # the page is the graphics plane as it was when the hardcopy began
    assert out == hardcopy(planes[0])
    assert sum(planes[0]) > 3000                            # staff, clef, menu frame


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
