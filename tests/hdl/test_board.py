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
        _testbench("term_display", "hdl/core/term_display.sv", ["+frame=" + frame, "+input=" + src])
        w, h, px = read_frame(frame)
    finally:
        shutil.rmtree(tmp)
    t = Terminal()
    t.feed(data)
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
    from tools.screen_text import read_image
    return read_image(path)


def frame_text(path, skip=()):
    """(terminal rows, panel rows, inverted cells, display segment codes)
    read back with the font (tools/screen_text.py)."""
    from tools.screen_text import screen_text
    return screen_text(path, skip=skip)


def expected_panel(display="    ", units=0):
    """The panel strip with no lights on."""
    from tools.gen_panel_labels import labels
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
