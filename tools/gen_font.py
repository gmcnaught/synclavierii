#!/usr/bin/env python3
"""Write hdl/core/font8x8.svh from third_party/font8x8/font8x8_basic.h
(Daniel Hepper's 8x8 font, public domain, after the IBM VGA font): 128
characters x 8 rows, bit 0 = leftmost pixel. Codes 0x00-0x1F (control
characters, blank in the font) hold the DEC special graphics set (VT100
"line drawing", characters 0x5F-0x7E), drawn here: box parts on the cell's
centre lines, scan lines, a few symbols.

Also hdl/core/font6x10.svh from third_party/font6x10/6x10-ascii.bdf (X.Org
6x10, public domain): the VT640's Tektronix alpha characters (tek_plane.sv,
tools/vt100.py), a 5 x 7 dot matrix in rows 0-9 (row 0 = top, baseline
under row 7, rows 8-9 descenders), bit 0 = leftmost.

And hdl/core/fontglass.svh from third_party/glasstty/glass-tty-vt220.txt
(svofski's Glass TTY VT220, Unlicense; tools/glass_extract.py): the VT220's
7 x 9 dot matrix in a 10-row cell (row 0 = top, baseline under row 7),
8 bits a row, bit 0 = leftmost: the text plane in VT640 mode (rows
doubled, 20 lines a text row). Codes 0x00-0x1F are the DEC special
graphics set as in font8x8.svh (the VT220's own glyphs).

Run:  python3 tools/gen_font.py
tests/hdl/test_board.py checks that the file is up to date; the board
bench (hdl/sim/lockstep.cpp, BOARD) reads the screen back with the same
glyphs (glyphs()).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "third_party", "font8x8", "font8x8_basic.h")
PATH = os.path.join(ROOT, "hdl", "core", "font8x8.svh")
SRC610 = os.path.join(ROOT, "third_party", "font6x10", "6x10-ascii.bdf")
PATH610 = os.path.join(ROOT, "hdl", "core", "font6x10.svh")
SRCGLASS = os.path.join(ROOT, "third_party", "glasstty", "glass-tty-vt220.txt")
PATHGLASS = os.path.join(ROOT, "hdl", "core", "fontglass.svh")


def special_graphics(font):
    """32 glyphs for DEC special graphics 0x5F-0x7E (in codes 0x00-0x1F)."""
    V, H, L, R = 0x08, 0xFF, 0x0F, 0xF8          # vertical, full/left/right horizontal

    def box(up, down, h):
        return [V if up else 0] * 3 + [h | (V if up or down else 0)] + [V if down else 0] * 4

    def scan(row):
        return [H if r == row else 0 for r in range(8)]
    g = {
        "_": [0] * 8,
        "`": [0x08, 0x1C, 0x3E, 0x7F, 0x3E, 0x1C, 0x08, 0x00],      # diamond
        "a": [0xAA, 0x55] * 4,                                      # checkerboard
        "b": font[ord("T")], "c": font[ord("F")], "d": font[ord("R")], "e": font[ord("L")],
        "f": [0x0E, 0x11, 0x11, 0x0E, 0, 0, 0, 0],                  # degree
        "g": font[ord("+")][:6] + [0x3E, 0],                        # plus-minus
        "h": font[ord("N")], "i": font[ord("V")],
        "j": box(True, False, L), "k": box(False, True, L),
        "l": box(False, True, R), "m": box(True, False, R),
        "n": box(True, True, H),
        "o": scan(0), "p": scan(1), "q": scan(3), "r": scan(5), "s": scan(7),
        "t": box(True, True, R), "u": box(True, True, L),
        "v": box(True, False, H), "w": box(False, True, H), "x": [V] * 8,
        "y": font[ord("<")], "z": font[ord(">")], "{": font[ord("n")],
        "|": font[ord("#")], "}": font[ord("L")], "~": font[ord(".")],
    }
    return [g[chr(0x5F + i)] for i in range(32)]


def glyphs():
    """128 lists of 8 row bytes (0x00-0x1F: DEC special graphics)."""
    rows = re.findall(r"\{\s*((?:0x[0-9A-Fa-f]{2}\s*,?\s*){8})\}", open(SRC).read())
    out = [[int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", r)] for r in rows]
    assert len(out) == 128 and all(len(g) == 8 for g in out)
    out[:32] = special_graphics(out)
    return out


def glyphs610():
    """128 lists of 10 row values (5 bits, bit 0 = leftmost; rows 0-9 from
    the top, baseline under row 7; codes outside 32-126 blank) from the
    6x10 BDF (every glyph BBX 6 10 0 -2, column 5 blank)."""
    out = [[0] * 10 for _ in range(128)]
    enc = None
    rows, inb = [], False
    for line in open(SRC610, encoding="latin-1"):
        f = line.split()
        if not f:
            continue
        if f[0] == "ENCODING":
            enc = int(f[1])
        elif f[0] == "BBX":
            assert f[1:5] == ["6", "10", "0", "-2"], f
        elif f[0] == "BITMAP":
            inb, rows = True, []
        elif f[0] == "ENDCHAR":
            inb = False
            if enc is not None and 32 <= enc < 127:
                for i, r in enumerate(rows):
                    v = int(r, 16) >> 3 & 0x1F                       # columns 0-4, bit 4 = leftmost
                    out[enc][i] = int("{:05b}".format(v)[::-1], 2)   # bit 0 = leftmost
        elif inb:
            rows.append(f[0])
    # [CHOICE] 6x10's punctuation is screen-style (a 3 x 3 plus for '.',
    # below the baseline); a dot-matrix terminal's is a 2 x 2 dot on the
    # baseline. SYN-5.3 draws beat ticks and augmentation dots with '.'.
    dot = int("01100"[::-1], 2)
    out[ord(".")] = [0] * 6 + [dot, dot] + [0, 0]
    out[ord(":")] = [0, 0, 0, dot, dot, 0, dot, dot, 0, 0]
    out[ord(",")] = [0] * 6 + [dot, dot, int("00100"[::-1], 2), int("01000"[::-1], 2)]
    out[ord(";")] = [0, 0, 0, dot, dot, 0, dot, dot, int("00100"[::-1], 2), int("01000"[::-1], 2)]
    return out


def glyphs_glass():
    """128 lists of 10 row bytes (bit 0 = leftmost; rows 0-9 from the top,
    baseline under row 7). Codes 0x01-0x1F: the VT220's DEC special graphics
    (VT100 characters 0x60-0x7E), as the font has them; 0x00 (DEC 0x5F) and
    0x7F blank. The VT220 repeats a line-drawing character's last dot
    column across the rest of the cell so lines join: here bit 6 into bit 7
    for the box parts and scan lines (0x0B-0x18)."""
    out, code = [[0] * 10 for _ in range(128)], None
    for line in open(SRCGLASS):
        line = line.strip()
        if line.startswith("code "):
            code, row = int(line[5:], 16), 0
        elif line:
            out[code][row] = sum(1 << i for i, ch in enumerate(line) if ch == "#")
            row += 1
    out[0x00] = out[0x7F] = [0] * 10
    for c in range(0x0B, 0x19):
        out[c] = [v | (v >> 6 & 1) << 7 for v in out[c]]
    return out


def text_glass():
    lines = ["// Generated by tools/gen_font.py from third_party/glasstty/glass-tty-vt220.txt",
             "// (svofski's Glass TTY VT220, Unlicense). Do not edit. Address",
             "// {character[6:0], row[3:0]}, rows 0-9 from the top (baseline under row 7);",
             "// bit 0 is the leftmost pixel. Codes 0x00-0x1F: DEC special graphics.",
             "function automatic logic [7:0] fontglass(input logic [10:0] a);",
             "    case (a)"]
    for c, g in enumerate(glyphs_glass()):
        for r, v in enumerate(g):
            if v:
                lines.append("        11'd%d: fontglass = 8'h%02x;" % (c * 16 + r, v))
    lines += ["        default: fontglass = 8'h00;", "    endcase", "endfunction", ""]
    return "\n".join(lines)


def text610():
    lines = ["// Generated by tools/gen_font.py from third_party/font6x10/6x10-ascii.bdf",
             "// (X.Org 6x10, public domain). Do not edit. Address {character[6:0], row[3:0]},",
             "// rows 0-9 from the top (baseline under row 7); bit 0 is the leftmost pixel.",
             "function automatic logic [4:0] font6x10(input logic [10:0] a);",
             "    case (a)"]
    for c, g in enumerate(glyphs610()):
        for r, v in enumerate(g):
            if v:
                lines.append("        11'd%d: font6x10 = 5'h%02x;" % (c * 16 + r, v))
    lines += ["        default: font6x10 = 5'h00;", "    endcase", "endfunction", ""]
    return "\n".join(lines)


def text():
    lines = ["// Generated by tools/gen_font.py from third_party/font8x8/font8x8_basic.h",
             "// (public domain). Do not edit. Address {character[6:0], row[2:0]};",
             "// bit 0 is the leftmost pixel.",
             "function automatic logic [7:0] font8x8(input logic [9:0] a);",
             "    case (a)"]
    for c, g in enumerate(glyphs()):
        for r, v in enumerate(g):
            if v:
                lines.append("        10'd%d: font8x8 = 8'h%02x;" % (c * 8 + r, v))
    lines += ["        default: font8x8 = 8'h00;", "    endcase", "endfunction", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    with open(PATH, "w") as f:
        f.write(text())
    print("wrote", PATH)
    with open(PATH610, "w") as f:
        f.write(text610())
    print("wrote", PATH610)
    with open(PATHGLASS, "w") as f:
        f.write(text_glass())
    print("wrote", PATHGLASS)
