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
panel cells may be inverted whole (a lit button) or carry the decimal point
in their corner.
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
    return w, h, bytes(255 if v > threshold else 0 for v in im.getdata())


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


def screen_text(path, skip=(), strict=True):
    """(terminal rows, panel rows, inverted) of a 640 x 480 picture.
    skip: (terminal row, column) cells to read as blank (e.g. under the
    pointer). inverted: {(panel row, column): True} for whole inverted cells.
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
    panel, inverted = [], {}
    for r in range(12):
        line = ""
        for c in range(80):
            ch, inv = get(cell(384 + 8 * r, c, 1), "panel row %d col %d" % (r, c), True)
            inverted[(r, c)] = inv
            line += ch
        panel.append(line.rstrip())
    return term, panel, inverted


def main():
    term, panel, inv = screen_text(sys.argv[1], strict=False)
    for ln in term:
        print(ln)
    print("-" * 80)
    for r, ln in enumerate(panel):
        marks = "".join("*" if inv.get((r, c)) else " " for c in range(80)).rstrip()
        print(ln + ("    [lit at columns: %s]" % [c for c, m in enumerate(marks) if m == "*"][:20]
                    if marks else ""))


if __name__ == "__main__":
    main()
