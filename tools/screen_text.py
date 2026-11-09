#!/usr/bin/env python3
"""Read the text back from a picture of the core's screen (term_display.sv):
a frame from the board simulation (PGM) or a MiSTer screenshot (PNG, needs
Pillow), 640 x 480.

    screen_text.py IMAGE          print the 24 terminal rows, a separator and
                                  the 12 panel rows ('*' after an inverted,
                                  i.e. lit, button label)

Layout: terminal rows of 8 x 16-pixel cells (font rows doubled) from line
0; panel rows of 8 x 8 cells from line 384. Each cell is matched against
the font (tools/gen_font.py); row 7 of a cell may be inverted (the cursor),
panel cells may be inverted whole (a lit button). The four display digits
(panel row 1, columns 11-14) are drawn as 7 segments and read back as their
codes (bit 0 = segment a ... bit 6 = g, bit 7 = decimal point), shown as
characters where the code is a known one, '?' otherwise. Panel row 2 (the
status counters) changes while a frame is drawn, so a digit there may read
as '?'.

The velocity keyboard (VPK) panel strip is recognised by panel row 0
starting " Display" (the ORK's is a rule): row 0 is the 2 x 16-character
display in two bracketed fields (columns 11-26 and 29-44), row 1 the
status counters, rows 2-11 the 160 button labels (row r = PBN 16(r-2)..);
the display is then returned as its 32 characters (a string).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def read_image(path, threshold=96):
    """(width, height, pixels): one byte per pixel, nonzero = lit."""
    if path.lower().endswith(".pgm"):
        d = open(path, "rb").read()
        magic, size, _maxval, px = d.split(b"\n", 3)
        assert magic == b"P5"
        w, h = map(int, size.split())
        return w, h, px
    from PIL import Image
    im = Image.open(path).convert("L")
    w, h = im.size
    return w, h, im.point(lambda v: 255 if v > threshold else 0).tobytes()


# 7-segment codes (NED 05-BUTT:077-OLDW DIGITS, and letters) as characters
SEG_CHARS = {0o077: "0", 0o006: "1", 0o133: "2", 0o117: "3", 0o146: "4", 0o155: "5",
             0o174: "6", 0o175: "6", 0o047: "7", 0o007: "7", 0o177: "8", 0o147: "9",
             0o157: "9", 0o100: "-", 0o000: " ", 0o171: "E", 0o120: "r", 0o163: "P",
             0o070: "L", 0o166: "H", 0o167: "A", 0o071: "C", 0o136: "d", 0o161: "F",
             0o134: "o", 0o124: "n", 0o034: "u", 0o170: "t", 0o156: "y", 0o076: "U"}


def seg_code(g):
    """The segment code of a display cell drawn by term_display.sv's
    seg_glyph (None if the cell is not such a drawing)."""
    a, f, b, gg, e, c, d = (g[0] == 0x1C, g[1] & 0x02, g[1] & 0x20, g[3] == 0x1C,
                            g[4] & 0x02, g[4] & 0x20, (g[6] & 0x7F) == 0x1C)
    code = (a and 1) | (bool(b) << 1) | (bool(c) << 2) | (d << 3) | (bool(e) << 4) | \
        (bool(f) << 5) | (gg << 6) | (bool(g[6] & 0x80) << 7)
    want = [0x1C if a else 0, (0x02 if f else 0) | (0x20 if b else 0),
            (0x02 if f else 0) | (0x20 if b else 0), 0x1C if gg else 0,
            (0x02 if e else 0) | (0x20 if c else 0), (0x02 if e else 0) | (0x20 if c else 0),
            0x1C if d else 0, 0]
    if [v & 0x7F for v in g] != want or (g[6] & 0x80) != (g[7] & 0x80):
        return None
    return code


def _match(font, g, where, inverted):
    """(character, was inverted) for glyph rows g; None if nothing matches."""
    m = [ch for ch in range(32, 127)
         if font[ch][:7] == g[:7] and g[7] in (font[ch][7], font[ch][7] ^ 0xFF)]
    if m:
        return chr(m[0]), False
    if inverted:
        gi = [v ^ 0xFF for v in g]
        m = [ch for ch in range(32, 127) if font[ch] == gi]
        if m:
            return chr(m[0]), True
        m = [ch for ch in range(32, 127)
             if font[ch][:6] == g[:6] and [v & 0x7F for v in g[6:]] == font[ch][6:]]
        if m:
            return chr(m[0]), False
    return None


def is_vpk(panel):
    """The panel rows (screen_text) are the VPK strip."""
    return panel[0].startswith(" Display")


def screen_text(path, skip=(), strict=True):
    """(terminal rows, panel rows, inverted, display) of a 640 x 480 picture.
    skip: (terminal row, column) cells to read as blank (e.g. under the
    pointer). inverted: {(panel row, column): True} for whole inverted cells.
    display: the ORK's 4 segment codes, or the VPK's 32 characters.
    strict: raise on an unreadable cell (else it reads as '?')."""
    from tools.gen_font import glyphs
    w, h, px = read_image(path)
    assert (w, h) == (640, 480), (w, h)
    font = glyphs()

    def cell(y0, c, step):
        return [sum(1 << b for b in range(8) if px[(y0 + step * k) * w + 8 * c + b]) for k in range(8)]

    def get(g, where, inverted=False):
        r = _match(font, g, where, inverted)
        if r is None:
            if strict:
                raise AssertionError("%s: no character matches %r" % (where, g))
            return "?", False
        return r
    term = []
    for r in range(24):
        line = ""
        for c in range(80):
            if (r, c) in skip:
                line += " "
                continue
            g = cell(16 * r, c, 2)
            if g != cell(16 * r + 1, c, 2):
                if strict:
                    raise AssertionError("terminal row %d col %d: font rows not doubled" % (r, c))
                line += "?"
                continue
            line += get(g, "terminal row %d col %d" % (r, c))[0]
        term.append(line.rstrip())
    panel, inverted, display = [], {}, []
    head = "".join((_match(font, cell(384, c, 1), "", False) or ("?",))[0] for c in range(8))
    vpk = head.startswith(" Display")
    status_row = 1 if vpk else 2
    for r in range(12):
        line = ""
        for c in range(80):
            g = cell(384 + 8 * r, c, 1)
            if not vpk and r == 1 and 11 <= c <= 14:           # display digits
                code = seg_code(g)
                if code is None and strict:
                    raise AssertionError("display digit %d: not a segment drawing %r" % (c - 11, g))
                display.append(code)
                line += "?" if code is None else SEG_CHARS.get(code & 0x7F, "?")
                continue
            if r == status_row:                               # live counters: may tear
                m = _match(font, g, "", True)
                ch, inv = m if m else ("?", False)
            else:
                ch, inv = get(g, "panel row %d col %d" % (r, c), True)
            inverted[(r, c)] = inv
            line += ch
        panel.append(line.rstrip())
    if vpk:
        row = panel[0].ljust(80)
        display = row[11:27] + row[29:45]
    return term, panel, inverted, display


def main():
    term, panel, inv, disp = screen_text(sys.argv[1], strict=False)
    for ln in term:
        print(ln)
    print("-" * 80)
    if is_vpk(panel):
        print("VPK display: [%s] [%s]" % (disp[:16], disp[16:]))
    else:
        print("display segment codes (octal): %s" % " ".join("---" if c is None else "%03o" % c for c in disp))
    for r, ln in enumerate(panel):
        marks = "".join("*" if inv.get((r, c)) else " " for c in range(80)).rstrip()
        print(ln + ("    [lit at columns: %s]" % [c for c, m in enumerate(marks) if m == "*"][:20]
                    if marks else ""))


if __name__ == "__main__":
    main()
