#!/usr/bin/env python3
"""Write third_party/glasstty/glass-tty-vt220.txt, the dot matrix of
svofski's Glass TTY VT220 font (https://github.com/svofski/glasstty,
Unlicense), from its Glass_TTY_VT220.ttf. tools/gen_font.py reads the text
file; this script is only needed to redo it (it needs fontTools).

    python3 tools/glass_extract.py Glass_TTY_VT220.ttf

The TTF draws each character as horizontal runs of dots on a 10 x 10 grid
(advance 500 units, 50 a dot column; rows 100 units apart, each run 50
high), every dot stretched one column to the right as the VT220 did. A run
from x0 to x1 is the dots x0/50 .. x1/50 - 2 (the stretch removed); row
0 is the top (y 750-800), the baseline is under row 7 (y 50-100), rows 8-9
are descenders. Codes 0x00-0x7E; 0x01-0x1F hold the VT220's DEC special
graphics (VT100 line drawing, characters 0x60-0x7E).

Output: per code, a line "code NN" (hex) and 10 lines of 8 characters,
'#' a dot, '.' none, column 0 leftmost.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "third_party", "glasstty", "glass-tty-vt220.txt")


def raster(font, code):
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    gs = font.getGlyphSet()
    pen = DecomposingRecordingPen(gs)
    gs[font.getBestCmap()[code]].draw(pen)
    rows, pts = [0] * 10, []
    for op, args in pen.value:
        if op == "moveTo":
            pts = [args[0]]
        elif op in ("lineTo", "qCurveTo", "curveTo"):
            pts += [a for a in args if a]
        else:                                     # closePath / endPath
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            assert x0 % 50 == 0 and x1 % 50 == 0 and y0 % 100 == 50 and y1 - y0 == 50, \
                (hex(code), x0, x1, y0, y1)
            for c in range(x0 // 50, x1 // 50 - 1):
                rows[(750 - y0) // 100] |= 1 << c
            pts = []
    return rows


def main():
    from fontTools.ttLib import TTFont
    font = TTFont(sys.argv[1])
    out = []
    for code in range(0x7F):
        out.append("code %02X" % code)
        out += ["".join("#" if r >> c & 1 else "." for c in range(8)) for r in raster(font, code)]
    open(OUT, "w").write("\n".join(out) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
