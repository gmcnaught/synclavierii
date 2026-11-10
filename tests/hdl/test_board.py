#!/usr/bin/env python3
"""The MiSTer core (hdl/core/synclavier_core.sv) in simulation.

Generated tables up to date; the PS/2 keyboard decoder; MIDI input; and, with
SYNCLAVIER_RELEASE_L set, the whole core from power-on: the boot loader
boots MONITOR from the F0 image (SD block transfers played by the bench),
leaving exactly the state sim/boot.py does, the run through CATALOG
matches the Python trace instruction for instruction, and the video frame
shows the same text as the terminal.

Needs Verilator (skipped otherwise).

Run:  python3 tests/hdl/test_board.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from sim.lockstep import BUILD_DIR, check, record  # noqa: E402

HAVE_VERILATOR = shutil.which("verilator") is not None


def test_boot_defaults_up_to_date():
    from tools.gen_boot_defaults import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_boot_defaults.py"


def test_panel_labels_up_to_date():
    from tools.gen_panel_labels import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_panel_labels.py"


def test_midi_tables_up_to_date():
    from tools.gen_midi_tables import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_midi_tables.py"


def test_fm_tables_up_to_date():
    from tools.gen_fm_tables import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_fm_tables.py"


def test_font_up_to_date():
    from tools.gen_font import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_font.py"


def _testbench(name, rtl, args=()):
    """Build and run a self-checking SystemVerilog testbench hdl/sim/NAME_tb.sv
    with the RTL file(s) `rtl` (a path or a tuple of paths)."""
    mdir = os.path.join(BUILD_DIR, name)
    os.makedirs(mdir, exist_ok=True)
    b = subprocess.run(["verilator", "--binary", "-Wno-fatal", "-Wno-WIDTH", "-Wno-UNUSED",
                        "-I" + os.path.join(ROOT, "hdl/core"),
                        "--top-module", name + "_tb", "-Mdir", mdir]
                       + [os.path.join(ROOT, r) for r in ((rtl,) if isinstance(rtl, str) else rtl)]
                       + [os.path.join(ROOT, "hdl/sim/%s_tb.sv" % name)],
                       capture_output=True, text=True)
    assert b.returncode == 0, "building %s_tb failed:\n%s" % (
        name, "\n".join(ln for ln in (b.stdout + b.stderr).splitlines()
                        if "rror" in ln or "%Warning" not in ln)[-3000:])
    p = subprocess.run([os.path.join(mdir, "V%s_tb" % name)] + list(args),
                       capture_output=True, text=True)
    assert p.returncode == 0 and "%s OK" % name in p.stdout, p.stdout + p.stderr
    return p.stdout


def test_audio_fifo():
    """Samples arriving with jitter play at a steady rate, in order; a stall
    is one underrun with the last sample held."""
    if not HAVE_VERILATOR:
        print("  skip test_audio_fifo (needs verilator)")
        return
    _testbench("audio_fifo", "hdl/core/audio_fifo.sv")


# every sequence term_display handles (tools/vt100.py), in one stream
VT100_STREAM = (
    b"\x1b[H\x1b[2J"
    b"\x1b[7;5H\x1b#3BIG TITLE\r\n\x1b#4\x1b[8;5HBIG TITLE\r\n"
    b"\x1b[9;1H\x1b#6WIDE LINE"
    b"\x1b[10;10H\x1b[7mREVERSE\x1b[0m normal \x1b[1;7mboth\x1b[m plain"
    b"\x1b(0\x1b[11;2Hlqqwqqk\x1b[12;2Hx  x  x\x1b[13;2Htqqnqqu\x1b[14;2Hmqqvqqj `afgopqrsy{|}~\x1b(B"
    b"\x1b[15;1Habcdefghijklmnop\x1b[15;5H\x1b[K\x1b[16;1Habcdefghij\x1b[16;5H\x1b[1K"
    b"\x1b[17;1Hwhole line\x1b[2K"
    b"\x1b[18;70H0123456789ABCDEFwrapped"
    b"\x1b7\x1b[20;1Hsaved\x1b8!"
    b"\x1d\x1b\x0cTEKTRONIX GRAPHICS SKIPPED\x18"
    b"\r\n\tT1\tT2\t\x08b"
    b"\x1b[21;40H\x1b[3Aup\x1b[2Bdn\x1b[5Crt\x1b[3Dlf\x1b[99;99HZ"
    b"\x1b[?25l\x1b=\x1b>\x07\x0e\x0f"
    b"\x1b[1;1H\x1bMtop\x1b[23;1H\x1bDindex\x1bEnext"
    b"\x1b[24;1Hs1\r\ns2\x0bs3\x0cend")


def _vt100_check(data, tag):
    from tools.vt100 import Terminal
    tmp = tempfile.mkdtemp()
    try:
        src = os.path.join(tmp, "in.bin")
        frame = os.path.join(tmp, "frame.pgm")
        open(src, "wb").write(data)
        out = _testbench("term_display", ("hdl/core/term_display.sv", "hdl/core/tek_plane.sv"),
                         ["+frame=" + frame, "+input=" + src])
        w, h, px = read_frame(frame)
    finally:
        shutil.rmtree(tmp)
    t = Terminal()
    t.feed(data)
    assert "keypad_app %d" % t.keypad in out, (tag, out, t.keypad)
    want = t.render()
    wide = t.attr[t.row] != 0
    cx0, cx1 = (16 * t.col, 16 * t.col + 16) if wide else (8 * t.col, 8 * t.col + 8)
    bad = []
    for y in range(384):
        for x in range(640):
            if 16 * t.row <= y < 16 * t.row + 16 and cx0 <= x < cx1:
                continue                                   # the cursor (blinks)
            if 600 <= x < 608 and 100 <= y < 108:
                continue                                   # the pointer
            if bool(px[y * w + x]) != bool(want[y * 640 + x]):
                bad.append((x, y))
    assert not bad, "%s: %d pixels differ from tools/vt100.py, first at %s (row %d)\n%s" % (
        tag, len(bad), bad[0], bad[0][1] // 16, "\n".join(t.text()))
    return t


def test_term_display_vt100():
    """The terminal's VT100 subset: the picture equals tools/vt100.py's,
    for a stream with every handled sequence and (with the image) the
    bytes ORK-LM sends for its welcome menu."""
    if not HAVE_VERILATOR:
        print("  skip test_term_display_vt100 (needs verilator)")
        return
    t = _vt100_check(VT100_STREAM, "synthetic")
    # four lines scrolled: the titles are now rows 2-4
    assert t.text()[2].startswith("    BIG TITLE") and t.attr[2:5] == [1, 2, 3], (t.text(), t.attr)
    image = os.environ.get("SYNCLAVIER_RELEASE_L")
    if not image:
        print("  skip ORK-LM welcome menu (needs SYNCLAVIER_RELEASE_L)")
        return
    from sim.rtp import run_seconds, start_rtp
    out = bytearray()
    cpu, dbg, _ = start_rtp(image, "ORK-LM")
    cpu.terminal.output = out.append
    run_seconds(cpu, dbg, 10)
    t = _vt100_check(bytes(out), "ORK-LM")
    assert "Select screen with arrow keys" in "\n".join(t.text())
    assert t.keypad                                         # ORK-LM sends ESC =


# VT640 graphics (docs/devices/vt640-graphics-terminal.md): text, vectors,
# points, alpha text with BS/CR/LF, data levels (erase, XOR), a clear and
# redraw, a double-width row, reverse cells, short-form addresses, DEL as
# LoY, and an ESC sequence inside graphics
VT640_STREAM = (
    b"\x1b[H\x1b[2JTitle line\x1b[3;10H\x1b[7mreverse\x1b[0m plain"
    b"\x1b[5;1H\x1b#6WIDE\x1b[24;70Hbottom"
    b"\x1d\x1b/0d"
    b"\x20\x60\x20\x40"                  # (0,0) move
    b"\x38\x70\x3f\x5f"                  # to (1023, 760) line
    b"\x20\x60\x3f\x5f"                  # to (1023, 0)
    b"\x2c\x6c\x30\x50"                  # (528?, 396) short forms follow
    b"\x7f\x55"                            # DEL as LoY, LoX only
    b"\x1c\x30\x60\x28\x40\x31\x41"   # points
    b"\x1d\x30\x60\x28\x40\x1f" b"Alpha\x08\x08AB\r\nNext line"
    b"\x1d\x1b/2d\x30\x60\x28\x40\x30\x60\x30\x40\x2c\x60\x30\x40"   # XOR box edge
    b"\x1b/1d\x1d\x20\x60\x20\x40\x38\x70\x3f\x5f"                     # erase the diagonal
    b"\x1b/0d\x1b1\x1b|ab\x1b\\x\x18"
    b"\x1b[10;20Hafter graphics"
)


def test_term_display_vt640():
    """VT640 mode: the picture equals tools/vt100.py Terminal(vt640=True)."""
    if not HAVE_VERILATOR:
        print("  skip test_term_display_vt640 (needs verilator)")
        return
    _vt640_check(VT640_STREAM, "vt640")
    # a clear and the same again: identical
    _vt640_check(VT640_STREAM + b"\x1d\x1b\x0c\x18" + VT640_STREAM, "vt640 twice")


def _vt640_check(data, tag):
    from tools.vt100 import Terminal
    tmp = tempfile.mkdtemp()
    try:
        src = os.path.join(tmp, "in.bin")
        frame = os.path.join(tmp, "frame.pgm")
        open(src, "wb").write(data)
        _testbench("term_display", ("hdl/core/term_display.sv", "hdl/core/tek_plane.sv"),
                   ["+frame=" + frame, "+input=" + src, "+vt640"])
        w, h, px = read_frame(frame)
    finally:
        shutil.rmtree(tmp)
    t = Terminal(vt640=True)
    t.feed(data)
    want = t.render()
    c0 = 8 + ((15 * t.col + 1) >> 1)
    bad = [(x, y) for y in range(480) for x in range(640)
           if not (20 * t.row <= y < 20 * t.row + 20 and c0 <= x < c0 + 16)   # the cursor
           and bool(px[y * w + x]) != bool(want[y * 640 + x])]
    assert sum(t.g) > 1000, sum(t.g)
    assert not bad, "%s: %d pixels differ from tools/vt100.py, first at %s" % (tag, len(bad), bad[0])
    return t


def test_panel_mouse():
    """Mouse packets -> pointer (clamped) and panel button presses."""
    if not HAVE_VERILATOR:
        print("  skip test_panel_mouse (needs verilator)")
        return
    _testbench("panel_mouse", "hdl/core/panel_mouse.sv")


def test_term_display_panel():
    """One clock per pixel (the MiSTer setting): terminal text, lit buttons
    shown inverted, display digits with the decimal point, the pointer."""
    if not HAVE_VERILATOR:
        print("  skip test_term_display_panel (needs verilator)")
        return
    from tools.gen_font import glyphs
    from tools.gen_panel_labels import labels
    tmp = tempfile.mkdtemp()
    try:
        frame = os.path.join(tmp, "frame.pgm")
        _testbench("term_display", ("hdl/core/term_display.sv", "hdl/core/tek_plane.sv"), ["+frame=" + frame])
        term, panel, inverted, display = frame_text(frame, skip={(6, 75)})   # (6, 75): under the pointer
        w, h, px = read_frame(frame)
    finally:
        shutil.rmtree(tmp)
    font, lab = glyphs(), labels()
    assert term[0] == "HELLO" and term[1] == "WORLD", term[:3]
    assert panel[1] == " Display  [1234]   Units 0004", panel[1]
    assert panel[2] == " Lag us 00012A3F   Underrun 0002   Overrun 0000   MIDI 0123 F8 Err 0000 9k6", panel[2]
    # the segment codes as written (NED DIGITS), decimal point on digit 2
    assert display == [0o006, 0o133 | 0o200, 0o117, 0o146], [oct(c) for c in display]
    # lit: HSus (word 0 bit 15), Bk1 (word 6 bit 0), Tb2 (word 6 bit 9)
    lit = {(0, 15), (6, 0), (6, 9)}
    for r in range(8):
        for c in range(16):
            assert panel[3 + r][5 * c:5 * c + 4].ljust(4) == lab[16 * r + c], (r, c)
            assert inverted[(3 + r, 5 * c)] == ((r, c) in lit), (r, c)
    # pointer: arrow tip at (600, 100), its row 4 is 5 pixels wide
    assert px[100 * w + 600] and not px[100 * w + 601]
    assert all(px[104 * w + 600 + i] for i in range(5)) and not px[104 * w + 605]


def test_term_display_stall_view():
    """The status line's stall view (stall_view = 1): lag by cause, seven
    fields of 11 columns (able_system.sv STALL_* order)."""
    if not HAVE_VERILATOR:
        print("  skip test_term_display_stall_view (needs verilator)")
        return
    tmp = tempfile.mkdtemp()
    try:
        frame = os.path.join(tmp, "frame.pgm")
        _testbench("term_display", ("hdl/core/term_display.sv", "hdl/core/tek_plane.sv"),
                   ["+frame=" + frame, "+stall"])
        term, panel, inverted, display = frame_text(frame, skip={(6, 75)})
    finally:
        shutil.rmtree(tmp)
    want = "".join(" %-3s %06X" % (name, 0x10000 * i + 0x1234 + i) for i, name in
                   enumerate(("Fch", "SCS", "Ply", "Xm", "IO", "FM", "Run")))
    assert panel[2] == want, (panel[2], want)


def test_term_display_vpk():
    """The VPK panel strip (vpk = 1): the 2 x 16 display, the status line,
    the 160 labels by PBN; a lit label (state 1, and 3) inverted in both
    blink phases, a blinking one (state 2) only in the second."""
    if not HAVE_VERILATOR:
        print("  skip test_term_display_vpk (needs verilator)")
        return
    tmp = tempfile.mkdtemp()
    try:
        frames = [os.path.join(tmp, "frame%d.pgm" % i) for i in (1, 2)]
        _testbench("term_display", ("hdl/core/term_display.sv", "hdl/core/tek_plane.sv"),
                   ["+vpk", "+frame=" + frames[0], "+frame2=" + frames[1]])
        shots = [frame_text(f, skip={(6, 75)}) for f in frames]   # (6, 75): under the pointer
    finally:
        shutil.rmtree(tmp)
    for phase, (term, panel, inverted, display) in enumerate(shots):
        assert term[0] == "HELLO" and term[1] == "WORLD", term[:3]
        assert display == " SYNCLAVIER 5.3 40 VOICES 36M   ", repr(display)   # 0x01 -> space
        lit = {33, 159} | ({108} if phase else set())
        want = expected_panel(vpk=True, display=display, lit=lit, status=panel[1])
        assert panel == want, "\n".join(panel + ["--- expected"] + want)
        assert panel[1] == " Lag us 00012A3F   Underrun 0002   Overrun 0000   MIDI 0123 F8 Err 0000 9k6", panel[1]
        for pbn in range(160):
            r, c = 2 + pbn // 16, 5 * (pbn % 16)
            assert all(inverted[(r, c + i)] == (pbn in lit) for i in range(4)), (phase, pbn)
            assert not inverted[(r, c + 4)]


def test_dev_scsi():
    """The SCSI host and disk (hdl/dev/dev_scsi.sv): the sequences of
    tests/sim/test_scsi.py, including MONITOR 5.3's manual last byte."""
    if not HAVE_VERILATOR:
        print("  skip test_dev_scsi (needs verilator)")
        return
    _testbench("dev_scsi", "hdl/dev/dev_scsi.sv")


def poly_stimulus(path, seed=1, ops=6000, bins=1, sectors=65536, last_voices=32, mono=False):
    """Stimulus for hdl/sim/dev_poly_tb.sv from sim/devices/poly.py: POLY.CHECK-
    style init, poly memory writes/reads, voices (loops, stereo master,
    PSWL rewrites, restarts), envelopes and volume ramps, random time steps,
    register reads and mixes, each with the model's answer. With bins > 1
    each bin gets its own tables and voices (channel 64 x bin + c).
    last_voices: voices in the last bin (M16); mono: mono voice cards."""
    import math
    import random
    from sim.devices.poly import PolySynth
    rng = random.Random(seed)
    p = PolySynth(sectors=sectors, bins=bins, last_voices=last_voices, mono=mono)
    end = p.sectors * 256
    out = []

    def t(ns):
        p.tick(ns)
        out.append("T %d 0" % ns)

    def w(r, v):
        p.write(0o154 + r, v & 0xFFFF)
        out.append("W %d %d" % (r, v & 0xFFFF))

    def rd(r):
        out.append("R %d %d" % (r, p.read(0o154 + r)))

    def mix():
        p.advance()
        l, r = p._mix()
        sat = lambda x: max(-32768, min(32767, x))
        out.append("X %d %d" % (sat(l), sat(r)))

    def fc(ch, f, *words):
        w(1, ch)
        w(2, f)
        for x in words:
            w(3, x)

    def two(v):
        v &= 0xFFFFFFF
        return [v >> 8 & 0xFFFF, (v >> 24) << 8 | v & 0xFF]

    # detection and init
    for ch in (1, 65, 129, 193):
        w(1, ch); w(1, ch); rd(1)
    fc(0, 12); rd(3); rd(3); rd(2)
    for b in range(4):                              # PSNUMV per bin (absent: as 32)
        fc(64 * b, 12); rd(3)
    for b in range(bins):
        for ch in range(64 * b, 64 * b + 64):
            fc(ch, 0, 0xFFFF, 0xFFFF, 0, 255, 0xFFFF, 0xFFFF, 0, 0, 255, 0, 0)
            if ch % 64 < 32:
                fc(ch, 33, 4095, 4095, 1, 4095, 4095, 0, 0)
                fc(ch, 40, 0, 0, 0, 0)
    # poly memory of each bin: tables at word 1000 (mono) and 9000 (stereo
    # frames), different in each bin; the next bin up (absent) drops writes
    for b in range(min(bins + 1, 4)):
        fc(64 * b, 16, *two(1000))
        for i in range(3000):
            w(3, int((20000 - 3000 * b) * math.sin(i / (7.0 + b))))
        fc(64 * b, 16, *two(9000))
        for i in range(2000):
            w(3, (i * (37 + b)) & 0xFFFF)
        fc(64 * b, 20, *two(995))
        for _ in range(12):
            rd(3)
        fc(64 * b, 16, *two(end - 2), 1 + b, 2, 3)  # crosses the end of the bin
        fc(64 * b, 20, *two(end - 2))
        for _ in range(3):
            rd(3)
        fc(64 * b, 20, *two(1 << 25))               # page 2: no memory
        rd(3)
    t(1000)
    for n in range(ops):
        op = rng.random()
        b = rng.randrange(bins)
        ch = rng.randrange(32) if rng.random() < 0.9 else rng.randrange(32, 70)
        ch = (64 * b + ch) & 0xFF if rng.random() < 0.98 else rng.randrange(256)
        if op < 0.05:                               # start a voice
            length = rng.choice([50, 300, 2900, 1999])
            loop = rng.choice([0, 0, 40, 250])
            base = rng.choice([1000, 9000, 1500])
            inc, mod = rng.randrange(1, 257), rng.randrange(1, 257)
            if inc > mod:
                inc, mod = mod, inc
            pi = rng.choice([1, 1, 2, 4])
            fc(ch, 10, 0)
            fc(ch, 0, *(two(-length) + two(base) + two(-loop) + two(pi)), inc - 1, 256 - mod,
               rng.choice([1, 3, 3]))
        elif op < 0.08:                             # envelope
            fc(ch, 33, rng.choice([4095, 4000, 3000]), rng.randrange(4096), rng.randrange(1, 300),
               rng.randrange(4096), rng.randrange(4096), rng.randrange(4096), rng.randrange(4096))
        elif op < 0.10:
            fc(ch, 35, rng.randrange(4096), rng.randrange(1, 100))
            fc(ch, 36, rng.randrange(4096))
        elif op < 0.13:                             # volumes
            fc(ch, 40, rng.randrange(4096), rng.randrange(4096), rng.randrange(4096), rng.randrange(4096))
        elif op < 0.14:
            fc(ch, 41, rng.randrange(4096), rng.randrange(4096))
        elif op < 0.15:                             # stereo master on/off
            fc(ch & ~1, 59, rng.randrange(2))
        elif op < 0.16:                             # PSWL rewrite on a sounding voice
            fc(ch, 0, *two(-rng.randrange(1, 3000)))
        elif op < 0.17:
            fc(ch, 10, rng.randrange(4))
        elif op < 0.19:
            fc(ch, rng.choice([8, 9]), rng.randrange(256))
        elif op < 0.45:                             # reads
            f = rng.choice([11, 11, 37, 36, 40, 41, 42, 43, 32, 34, 0, 3, 7, 8, 9, 10, 12, 50])
            w(1, ch); w(2, f); rd(3); rd(2)
        elif op < 0.55:
            mix()
        else:
            t(rng.choice([1, 50, 333, 999, 3000, 9900, 20000, 40000, 123456]))
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    return len(out)


def test_dev_poly():
    """The poly synth (hdl/dev/dev_poly.sv) against sim/devices/poly.py:
    every register read and mix of a random register stream."""
    if not HAVE_VERILATOR:
        print("  skip test_dev_poly (needs verilator)")
        return
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".stim", delete=False) as f:
        path = f.name
    try:
        # a 3200 (1 bin, 32 MB); a 6400 (2 bins); 4 bins (the most SYN-5.3 looks for);
        # M16: a part-filled last bin (4, 8, 20 voices), mono voice cards
        for bins, units, last, mono in ((1, 256, 32, False), (2, 128, 32, False),
                                        (4, 64, 32, False), (1, 32, 4, True),
                                        (3, 64, 8, False), (2, 96, 20, True)):
            poly_stimulus(path, bins=bins, sectors=units * 256, last_voices=last, mono=mono)
            out = _testbench("dev_poly", "hdl/dev/dev_poly.sv",
                             args=["+stim=" + path, "+bins=%d" % bins, "+units=%d" % units,
                                   "+last=%d" % last, "+mono=%d" % mono])
            print("  %d bin(s), last %d%s: %s" % (bins, last, ", mono" if mono else "",
                  [ln for ln in out.splitlines() if "dev_poly OK" in ln][0]))
    finally:
        os.unlink(path)


def vpk_stimulus(path, seed=1, ops=4000):
    """Stimulus for hdl/sim/dev_vpk_tb.sv from sim/devices/synth.py
    VelocityKeyboard: KEYBOARD.CHECK, KCR reads, key scans with velocity
    and pressure reads, analog/switch reads, button scans, light and
    display writes, random host events, each read with the model's answer."""
    import random
    from sim.devices.synth import VelocityKeyboard
    rng = random.Random(seed)
    kb = VelocityKeyboard()
    out = []

    def w(r, v):
        kb.write(0o130 + r, v & 0xFFFF)
        out.append("W %d %d" % (r, v & 0xFFFF))

    def rd(r=0):
        out.append("R %d %d" % (r, kb.read(0o130 + r)))

    def request(req):
        w(1, 1); w(0, req); w(1, 0o41); w(1, 1); w(1, 0o101); rd(); w(1, 1)

    def host(op, a, d=0):
        out.append("H %d %d %d" % (op, a, d))
        if op == 0:
            kb.press_key(a + 9, True, d)
        elif op == 1:
            kb.press_key(a + 9, False)
        elif op == 2:
            kb.press_button(a, bool(d & 1))
        elif op == 3:
            kb.analog[a & 7] = d
        elif op == 4:
            kb.switches = d
        else:
            kb.pressure[a] = d

    w(1, 0o105); rd(); w(1, 0o005)
    for _ in range(ops):
        x = rng.random()
        if x < 0.2:
            r = rng.random()
            if r < 0.45:
                host(rng.choice((0, 1)), rng.randrange(76), rng.randrange(128))
            elif r < 0.7:
                host(2, rng.randrange(160), rng.randrange(2))
            elif r < 0.85:
                host(3, rng.randrange(8), rng.randrange(256))
            elif r < 0.92:
                host(4, 0, rng.randrange(256))
            else:
                host(5, rng.randrange(80), rng.randrange(256))
        elif x < 0.35:                       # KCR (144-TIM3)
            w(0, 0); w(1, 0); w(1, 0o40); w(1, 0); w(1, 0o100); rd(); rd(); w(1, 0)
        elif x < 0.55:
            so = rng.randrange(6)
            request(0o417 | so << 4)
            request(rng.randrange(80))
        elif x < 0.65:
            request(0o200 | rng.choice((rng.randrange(80), rng.randrange(88, 96))))
        elif x < 0.75:
            request(0o600 | rng.choice((0, rng.randrange(1, 12))))
        elif x < 0.87:                       # light (mode 3)
            a, st = rng.randrange(170), rng.randrange(4)
            w(1, 3); w(0, a << 8 | st); w(1, 0o43); w(1, 3)
            if a < 160:
                out.append("L %d %d" % (a, kb.lights[a]))
        else:                                # display (mode 2)
            a, ch = rng.choice((rng.randrange(32), rng.choice((32, 36, 48, 52)))), rng.randrange(256)
            w(1, 2); w(0, a << 8 | ch); w(1, 0o42); w(1, 2)
            if a < 32:
                out.append("C %d %d" % (a, kb.chars[a]))
        if rng.random() < 0.02:              # an SMPTE-style 20/260 write: no EXW
            w(1, 0o20); w(1, 0o260); w(1, 0)
    open(path, "w").write("\n".join(out) + "\n")


def test_dev_vpk():
    """The velocity keyboard (hdl/dev/dev_vpk.sv) against sim/devices/synth.py."""
    if not HAVE_VERILATOR:
        print("  skip test_dev_vpk (needs verilator)")
        return
    import tempfile
    for seed in (1, 2, 3):
        with tempfile.NamedTemporaryFile(suffix=".stim", delete=False) as f:
            path = f.name
        try:
            vpk_stimulus(path, seed)
            out = _testbench("dev_vpk", "hdl/dev/dev_vpk.sv", args=["+stim=" + path])
            print("  " + [ln for ln in out.splitlines() if "dev_vpk OK" in ln][0])
        finally:
            os.unlink(path)


def midi_stimulus(path, seed=1, ops=6000):
    """Stimulus for hdl/sim/dev_midi_tb.sv from sim/devices/midi.py
    MidiSubsystem: SYN-5.3's detection and FIFO reset sequence, then random
    selects (16, 17, 8, 32, others), port/reset writes, register reads,
    output bytes and input bursts (some past the 64-byte FIFO)."""
    import random
    from sim.devices.midi import MidiSubsystem
    rng = random.Random(seed)
    card = MidiSubsystem()
    out = []

    def w(r, v):
        card.write(0o70 + r, v & 0xFFFF)
        out.append("W %d %d" % (r, v & 0xFFFF))

    def rd(r):
        out.append("R %d %d" % (r, card.read(0o70 + r)))

    def rx(b):
        card.receive(b)
        out.append("B %d" % b)

    w(0, 16); rd(0); rd(1)                          # INIT.MIDI.SUBSYSTEMS
    for j in range(8, 13):
        w(1, j); rd(2); w(2, 0)
    w(1, 0); w(0, 17); rd(0)
    for _ in range(ops):
        x = rng.random()
        if x < 0.1:
            w(0, rng.choice((16, 16, 16, 17, 8, 32, rng.randrange(1 << 16))))
        elif x < 0.2:
            w(1, rng.choice((0, 1, 2, 3, 4, 4, 4, 12, rng.randrange(1 << 16))))
        elif x < 0.45:
            rd(rng.randrange(4))
        elif x < 0.6:
            w(2, rng.randrange(1 << 16))
        elif x < 0.65:
            w(3, rng.randrange(1 << 16))
        elif x < 0.75:
            for _ in range(rng.choice((1, 3, 3, 20, 70))):
                rx(rng.randrange(256))
        else:                                      # SCAN.MIDI: drain the input
            w(0, 16)
            while card.fifo and rng.random() < 0.95:
                rd(1); w(1, 4); rd(2)
            rd(1)
    out += ["O %d" % b for _, b in card.out]
    open(path, "w").write("\n".join(out) + "\n")
    assert card.dropped and len(card.out) > 100, (card.dropped, len(card.out))


def test_dev_midi():
    """The MIDI subsystem card (hdl/dev/dev_midi.sv) against sim/devices/midi.py."""
    if not HAVE_VERILATOR:
        print("  skip test_dev_midi (needs verilator)")
        return
    import tempfile
    for seed in (1, 2, 3):
        with tempfile.NamedTemporaryFile(suffix=".stim", delete=False) as f:
            path = f.name
        try:
            midi_stimulus(path, seed)
            out = _testbench("dev_midi", "hdl/dev/dev_midi.sv", args=["+stim=" + path])
            print("  " + [ln for ln in out.splitlines() if "dev_midi OK" in ln][0])
        finally:
            os.unlink(path)


def dig_stm_stimulus(path, seed=1, calls=1500):
    """Stimulus for hdl/sim/dig_stm_tb.sv from sim/devices/digstm.py
    DigitalStm: a small random source (mono or stereo; seed 3 none), then
    SYN-5.3's sequence (get_rate, latch, start, samples until 256, import or
    toss, lmax, rmax) with random rates, stereo flags, early imports
    (underflow), stops, releases, rate changes, a remount, and CPU ticks of
    random length between the calls."""
    import random
    from sim.devices.digstm import DigitalStm, Source
    rng = random.Random(seed)
    out = []
    src = None
    if seed != 3:
        ch = 2 if seed % 2 == 0 else 1
        frames = rng.randrange(1500, 4000)
        samples = [rng.choice((0, -32768, 32767, rng.randrange(-32768, 32768),
                               rng.randrange(-300, 300))) for _ in range(frames * ch)]
        src = Source(samples, ch, rng.choice((441, 480, 505, 1023, 320)))
        data = src.to_bytes()
        src = Source.from_bytes(data)
        words = [data[i] << 8 | data[i + 1] for i in range(0, len(data), 2)]
        out.append("F %d %s" % (len(words), " ".join(map(str, words))))
    else:
        out.append("A")
    ds = DigitalStm(src)

    class Poly:
        def write(self, dev, v):
            assert dev == 0o157
            out.append("W %d" % v)

    class Cpu:
        r = [0] * 16
        time_ns = 0
    cpu = Cpu()
    ds.poly = Poly()

    def tick(ns, k):
        if k:
            cpu.time_ns += ns * k
            out.append("T %d %d" % (ns, k))

    def call(n, r0=None, r1=None, r2=None):
        r = cpu.r
        r[0] = rng.randrange(1 << 16) if r0 is None else r0
        r[1] = rng.randrange(1 << 16) if r1 is None else r1
        r[2] = rng.randrange(1 << 16) if r2 is None else r2
        args = r[0], r[1], r[2]
        ds.call(cpu, n)                          # its D157 writes ("W") go first
        wr = n in (65, 66, 69, 70, 72, 74, 76)   # the routines with a result
        assert wr or r[0] == args[0]
        out.append("C %d %d %d %d %d %d" % (n - 64, args[0], args[1], args[2], int(wr),
                                            r[0] if wr else 0))

    call(74)
    for _ in range(calls):
        x = rng.random()
        if x < 0.04:
            call(72, 0, rng.choice((0, 1, 1, 3)), rng.choice((441, 480, 505, 0, 2000, 1023, 77)))
            call(64)
        elif x < 0.06:
            call(rng.choice((67, 73)))
        elif x < 0.08:
            call(75, rng.choice((400, 441, 505, 0, 1024, 1023, 1)))
        elif x < 0.10:
            call(rng.choice((74, 76, 66)))
        elif x < 0.11:
            out.append("M")                     # the same file again: its rate again
            ds.mount(src)
        else:
            # wait for 256 frames (or not: an early import underflows)
            ns = rng.choice((333, 666, 999, rng.randrange(1, 1000)))
            while rng.random() < 0.97:
                call(65)
                if cpu.r[0] >= 256 or not ds.running:
                    break
                tick(ns, rng.randrange(50, 3000))
            call(rng.choice((68, 68, 71)))
            call(69)
            call(70)
        tick(rng.choice((333, 666, 999)), rng.randrange(0, 40))
    open(path, "w").write("\n".join(out) + "\n")
    return ds


def test_dig_stm():
    """The digital STM handler (hdl/core/dig_stm.sv) against
    sim/devices/digstm.py: results, D157 writes, frame timing."""
    if not HAVE_VERILATOR:
        print("  skip test_dig_stm (needs verilator)")
        return
    import tempfile
    for seed in (1, 2, 3):
        with tempfile.NamedTemporaryFile(suffix=".stim", delete=False) as f:
            path = f.name
        try:
            ds = dig_stm_stimulus(path, seed)
            if seed != 3:
                assert ds.imports > 100 and ds.calls.get(71, 0) > 20, (ds.imports, ds.calls)
            out = _testbench("dig_stm", "hdl/core/dig_stm.sv", args=["+stim=" + path])
            print("  " + [ln for ln in out.splitlines() if "dig_stm OK" in ln][0])
        finally:
            os.unlink(path)


def test_ps2_ascii():
    if not HAVE_VERILATOR:
        print("  skip test_ps2_ascii (needs verilator)")
        return
    _testbench("ps2_ascii", "hdl/core/ps2_ascii.sv")


def test_midi_vpk():
    """MIDI messages -> velocity keyboard host ops; knob pulse and tap timing."""
    if not HAVE_VERILATOR:
        print("  skip test_midi_vpk (needs verilator)")
        return
    _testbench("midi_vpk", "hdl/core/midi_vpk.sv")


def test_midi_in():
    """MIDI bytes -> clavier/panel words; program change button timing."""
    if not HAVE_VERILATOR:
        print("  skip test_midi_in (needs verilator)")
        return
    _testbench("midi_in", "hdl/core/midi_in.sv")


def test_midi_card():
    """MIDI bytes -> midi_in -> midi_card_feed: the bytes the MIDI card
    receives (panel controls kept back); MIDI out (midi_uart_tx) at 31250
    and 9600 baud."""
    if not HAVE_VERILATOR:
        print("  skip test_midi_card (needs verilator)")
        return
    _testbench("midi_card", ("hdl/core/midi_in.sv", "hdl/core/midi_card_feed.sv",
                             "hdl/dev/dev_midi.sv"))


def read_frame(path):
    """(width, height, bytes) of a binary PGM."""
    from tools.screen_text import read_image
    return read_image(path)


def frame_text(path, skip=()):
    """(terminal rows, panel rows, inverted cells, display segment codes)
    read back with the font (tools/screen_text.py)."""
    from tools.screen_text import screen_text
    return screen_text(path, skip=skip)


def expected_panel(display="    ", units=0, vpk=False, lit=(), status=None):
    """The panel strip with no lights on (the ORK's), or the VPK's with the
    32-character display, status line `status` and PBNs `lit` (only for
    the inverted-cell check: the text is the same)."""
    from tools.gen_panel_labels import labels, vpk_labels
    if vpk:
        lab = vpk_labels()
        rows = [(" Display  [%s][%s]" % (display[:16], display[16:])).rstrip(), status]
        for r in range(10):
            rows.append(" ".join(lab[16 * r:16 * r + 16]).rstrip())
        return rows
    lab = labels()
    rows = ["-" * 80, (" Display  [%s]   Units %04X" % (display, units)).rstrip(),
            " Lag us 00000000   Underrun 0000   Overrun 0000   MIDI 0000 00 Err 0000 31k"]
    for r in range(8):
        rows.append(" ".join(lab[16 * r:16 * r + 16]).rstrip())
    rows.append(" Click a button to press it.   MIDI: ch 1-15 keys, ch 16 buttons, prog = timbre")
    return rows


def test_board_boots_release_l():
    image = os.environ.get("SYNCLAVIER_RELEASE_L")
    if not image or not HAVE_VERILATOR:
        print("  skip test_board_boots_release_l (needs SYNCLAVIER_RELEASE_L and verilator)")
        return
    from sim.boot import boot_from_image
    cpu, _ = boot_from_image(image, "03-SYSTD", f1="18-UTILS")
    lines = ["CATALOG\r"]

    def on_wait(cpu):
        if lines:
            cpu.terminal.feed(lines.pop(0))
            return True
        return False
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "monitor.trace")
        frame = os.path.join(tmp, "frame.pgm")
        n = record(cpu, path, 5_000_000, on_wait=on_wait)
        ok, text = check(path, top="board", frame=frame)
        assert ok, text
        assert "state matches" in text, text
        screen = [ln[1:] for ln in text.split("screen:\n", 1)[1].splitlines()[:24]]
        term, panel, inverted, display = frame_text(frame)
        assert term == screen
        assert not any(inverted.values())
        # status line: no throttle in the bench (lag 0); the bench runs faster
        # than real time, so the audio FIFO overruns there
        import re
        assert re.fullmatch(r" Lag us 00000000   Underrun [0-9A-F?]{4}   Overrun [0-9A-F?]{4}   MIDI 0000 00 Err 0000 31k", panel[2]), panel[2]
        assert panel[:2] + panel[3:] == expected_panel()[:2] + expected_panel()[3:], "\n".join(panel)
    finally:
        shutil.rmtree(tmp)
    assert n > 1_000_000
    assert screen[0] == "Booting MONITOR from F0"
    assert "N.E.D. ABLE Series System Monitor - 1 December 1985" in screen
    assert "Catalog contains 7 entries, 375 sectors used, 25 sectors remaining" in screen
    assert screen[12] == "Ready >"


def test_board_state_image_ork_lm():
    """ORK-LM on the core from a state image: the simulator runs ORK-LM to
    its main loop (8 s) and writes a state image there (tools/state_image.py);
    the core loads it from S2 and must equal the trace's start state, then
    match it through the timbre recall and a held C4 (5M instructions),
    every audio sample included; the panel shows the lights and display."""
    image = os.environ.get("SYNCLAVIER_RELEASE_L")
    if not image or not HAVE_VERILATOR:
        print("  skip test_board_state_image_ork_lm (needs SYNCLAVIER_RELEASE_L and verilator)")
        return
    from sim.lockstep import ork_lm_note_actions
    from sim.rtp import start_rtp
    from tools.state_image import state_bytes
    cpu, dbg, _ = start_rtp(image, "ORK-LM")
    actions = ork_lm_note_actions(cpu, dbg, image)
    tmp = tempfile.mkdtemp()
    try:
        state = os.path.join(tmp, "ork.sst")
        path = os.path.join(tmp, "ork.trace")
        frame = os.path.join(tmp, "frame.pgm")
        open(state, "wb").write(state_bytes(cpu))
        n = record(cpu, path, 5_000_000, actions=actions, audio=True)
        ok, text = check(path, top="board", state=state, frame=frame)
        assert ok, text
        assert "state matches" in text and "804572 audio samples" in text, text
        term, panel, inverted, display = frame_text(frame)
    finally:
        shutil.rmtree(tmp)
    assert n == 5_000_000
    kb = cpu.keyboard
    assert display == [kb.display[1] >> 8, kb.display[1] & 0o377,
                       kb.display[0] >> 8, kb.display[0] & 0o377], [oct(c) for c in display]
    for r in range(8):                                 # lights as the model has them
        for c in range(16):
            assert inverted[(3 + r, 5 * c)] == bool(kb.lights[r] >> c & 1), (r, c)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
