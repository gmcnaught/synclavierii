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


def test_font_up_to_date():
    from tools.gen_font import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_font.py"


def _testbench(name, rtl):
    """Build and run a self-checking SystemVerilog testbench hdl/sim/NAME_tb.sv."""
    mdir = os.path.join(BUILD_DIR, name)
    os.makedirs(mdir, exist_ok=True)
    subprocess.run(["verilator", "--binary", "-Wno-fatal", "-Wno-WIDTH", "-Wno-UNUSED",
                    "--top-module", name + "_tb", "-Mdir", mdir,
                    os.path.join(ROOT, rtl), os.path.join(ROOT, "hdl/sim/%s_tb.sv" % name)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p = subprocess.run([os.path.join(mdir, "V%s_tb" % name)], capture_output=True, text=True)
    assert p.returncode == 0 and "%s OK" % name in p.stdout, p.stdout + p.stderr


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


def frame_text(path):
    """The 80 x 24 text in a frame from term_display.sv: each character cell
    is 8 x 16 pixels (font rows doubled) from line 48, matched against the
    font (row 7 may be inverted: the cursor)."""
    from tools.gen_font import glyphs
    w, h, px = read_frame(path)
    assert (w, h) == (640, 480)
    font = glyphs()
    lines = []
    for r in range(24):
        line = ""
        for c in range(80):
            g = []
            for k in range(8):
                y = 48 + 16 * r + 2 * k
                a = sum(1 << b for b in range(8) if px[y * w + 8 * c + b])
                a2 = sum(1 << b for b in range(8) if px[(y + 1) * w + 8 * c + b])
                assert a == a2, "row %d col %d: font row %d not doubled" % (r, c, k)
                g.append(a)
            m = [ch for ch in range(32, 127)
                 if font[ch][:7] == g[:7] and g[7] in (font[ch][7], font[ch][7] ^ 0xFF)]
            assert m, "row %d col %d: no character matches %r" % (r, c, g)
            line += chr(m[0])
        lines.append(line.rstrip())
    border = sum(1 for y in list(range(48)) + list(range(432, 480)) for x in range(w) if px[y * w + x])
    assert border == 0, "pixels outside the text area"
    return lines


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
        assert frame_text(frame) == screen
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
