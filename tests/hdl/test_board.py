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


def test_font_up_to_date():
    from tools.gen_font import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_font.py"


def _testbench(name, rtl, args=()):
    """Build and run a self-checking SystemVerilog testbench hdl/sim/NAME_tb.sv."""
    mdir = os.path.join(BUILD_DIR, name)
    os.makedirs(mdir, exist_ok=True)
    subprocess.run(["verilator", "--binary", "-Wno-fatal", "-Wno-WIDTH", "-Wno-UNUSED",
                    "-I" + os.path.join(ROOT, "hdl/core"),
                    "--top-module", name + "_tb", "-Mdir", mdir,
                    os.path.join(ROOT, rtl), os.path.join(ROOT, "hdl/sim/%s_tb.sv" % name)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p = subprocess.run([os.path.join(mdir, "V%s_tb" % name)] + list(args),
                       capture_output=True, text=True)
    assert p.returncode == 0 and "%s OK" % name in p.stdout, p.stdout + p.stderr


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
        _testbench("term_display", "hdl/core/term_display.sv", ["+frame=" + frame])
        term, panel = frame_text(frame, inverted=True)
        w, h, px = read_frame(frame)
    finally:
        shutil.rmtree(tmp)
    font, lab = glyphs(), labels()
    assert term[0] == "HELLO" and term[1] == "WORLD", term[:3]
    assert panel[1] == " Display  [1234]   Units 0004", panel[1]
    # decimal point: digit 2 (column 12) has the corner pixel on rows 6-7
    assert all(px[(392 + k) * w + 8 * 12 + 7] for k in (6, 7))
    assert not any(px[(392 + k) * w + 8 * 11 + 7] for k in range(8))
    # lit: HSus (word 0 bit 15), Bk1 (word 6 bit 0), Tb2 (word 6 bit 9)
    lit = {(0, 15), (6, 0), (6, 9)}
    for r in range(8):
        for c in range(16):
            assert panel[3 + r][5 * c:5 * c + 4].ljust(4) == lab[16 * r + c], (r, c)
            assert _inverted[(3 + r, 5 * c)] == ((r, c) in lit), (r, c)
    # pointer: arrow tip at (600, 100), its row 4 is 5 pixels wide
    assert px[100 * w + 600] and not px[100 * w + 601]
    assert all(px[104 * w + 600 + i] for i in range(5)) and not px[104 * w + 605]


def test_ps2_ascii():
    if not HAVE_VERILATOR:
        print("  skip test_ps2_ascii (needs verilator)")
        return
    _testbench("ps2_ascii", "hdl/core/ps2_ascii.sv")


def test_midi_in():
    """MIDI bytes -> clavier/panel words; program change button timing."""
    if not HAVE_VERILATOR:
        print("  skip test_midi_in (needs verilator)")
        return
    _testbench("midi_in", "hdl/core/midi_in.sv")


def read_frame(path):
    """(width, height, bytes) of a binary PGM."""
    d = open(path, "rb").read()
    magic, size, _maxval, px = d.split(b"\n", 3)
    assert magic == b"P5"
    w, h = map(int, size.split())
    return w, h, px


_inverted = {}       # (panel row, column) -> read back as an inverted glyph


def _match(font, g, row_label, inverted=False, key=None):
    """The character whose glyph is g (row 7 may be inverted: the cursor;
    with inverted=True a whole inverted glyph matches too)."""
    m = [ch for ch in range(32, 127)
         if font[ch][:7] == g[:7] and g[7] in (font[ch][7], font[ch][7] ^ 0xFF)]
    inv = False
    if not m and inverted:
        gi = [v ^ 0xFF for v in g]
        m = [ch for ch in range(32, 127) if font[ch] == gi]
        inv = bool(m)
    if not m and inverted:                                     # decimal point corner
        m = [ch for ch in range(32, 127)
             if font[ch][:6] == g[:6] and [v & 0x7F for v in g[6:]] == font[ch][6:]]
    assert m, "%s: no character matches %r" % (row_label, g)
    if key is not None:
        _inverted[key] = inv
    return chr(m[0])


def frame_text(path, inverted=False):
    """(terminal, panel) text in a frame from term_display.sv: 24 terminal
    rows of 8 x 16-pixel cells (font rows doubled) from line 0, then 12
    panel rows of 8 x 8 cells from line 384; matched against the font."""
    from tools.gen_font import glyphs
    w, h, px = read_frame(path)
    assert (w, h) == (640, 480)
    font = glyphs()

    def cell(y0, c, step):
        return [sum(1 << b for b in range(8) if px[(y0 + step * k) * w + 8 * c + b]) for k in range(8)]
    term = []
    for r in range(24):
        line = ""
        for c in range(80):
            if inverted and 16 * r <= 100 < 16 * r + 16 and c == 75:
                line += " "                                    # the pointer's cell
                continue
            g = cell(16 * r, c, 2)
            assert g == cell(16 * r + 1, c, 2), "row %d col %d: font rows not doubled" % (r, c)
            line += _match(font, g, "terminal row %d col %d" % (r, c))
        term.append(line.rstrip())
    panel = []
    for r in range(12):
        panel.append("".join(_match(font, cell(384 + 8 * r, c, 1), "panel row %d col %d" % (r, c),
                                    inverted, (r, c))
                             for c in range(80)).rstrip())
    return term, panel


def expected_panel(display="    ", units=0):
    """The panel strip with no lights on."""
    from tools.gen_panel_labels import labels
    lab = labels()
    rows = ["-" * 80, (" Display  [%s]   Units %04X" % (display, units)).rstrip(), ""]
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
        term, panel = frame_text(frame)
        assert term == screen
        assert panel == expected_panel(), "\n".join(panel)
    finally:
        shutil.rmtree(tmp)
    assert n > 1_000_000
    assert screen[0] == "Booting MONITOR from F0"
    assert "N.E.D. ABLE Series System Monitor - 1 December 1985" in screen
    assert "Catalog contains 7 entries, 375 sectors used, 25 sectors remaining" in screen
    assert screen[12] == "Ready >"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
