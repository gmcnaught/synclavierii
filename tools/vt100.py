#!/usr/bin/env python3
"""Reference model of the core's system terminal (hdl/core/term_display.sv):
the subset of a VT100 (with a VT640's Tektronix graphics passages skipped)
that Release L's programs use, and the picture term_display draws.

    vt100.py BYTES_FILE           print the 24 x 80 screen it gives

ORK-LM's welcome menu uses: cursor addressing (ESC [ r ; c H), erase
(ESC [ J / K), reverse video (ESC [ 7 m / 0 m), the DEC line-drawing set
(ESC ( 0 / ESC ( B), double-height lines (ESC # 3 / 4), keypad mode
(ESC =), and Tektronix graphics (GS ... CAN). Handled:

  printable   written at the cursor (bit 7 ignored); in the line-drawing set
              0x5F-0x7E become glyphs 0x00-0x1F (tools/gen_font.py); with
              the reverse attribute. Pending wrap at column 80 as on a VT100.
  CR LF BS HT LF/VT/FF = line feed (scrolling at the bottom); BEL, SO, SI,
              CAN, SUB and other controls ignored.
  GS          Tektronix graphics: everything up to CAN is skipped.
  ESC [ ... final   CSI with up to 4 numeric parameters (and '?'):
              H f  cursor to (p1, p2), 1-based, default 1
              A B C D  cursor up/down/right/left by p1 (default 1)
              J    erase in display (0 to end, 1 to cursor, 2 all)
              K    erase in line (0 to end, 1 to cursor, 2 all)
              m    0 normal, 7 reverse (others ignored)
              others ignored
  ESC # 3/4/6/5  line attribute: double-height top/bottom, double-width,
              single (ESC # 8 ignored); erasing whole lines with J resets it
  ESC ( c, ESC ) c   character set: ESC ( 0 line drawing, others ASCII (G0);
              G1 ignored
  ESC 7 / 8   save / restore cursor and attribute
  ESC D / E / M   index, next line, reverse index (at the top: no scroll)
  ESC c       reset: clear, home, normal
  ESC =, ESC >, ESC FF and other ESC c: ignored

Picture (640 x 384 terminal area): row r is lines 16r-16r+15; normal rows
show columns 0-79 at 8 pixels, each font row twice; double-width rows show
columns 0-39 at 16 pixels (each pixel twice); double-height rows also
stretch the top (rows 0-3) or bottom (rows 4-7) half of the glyph over the
16 lines (each font row 4 times). Reverse cells are inverted. The cursor is
not drawn (it blinks).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROWS, COLS = 24, 80
NORMAL, DH_TOP, DH_BOTTOM, DW = 0, 1, 2, 3


class Terminal:
    def __init__(self):
        self.reset()

    def reset(self):
        self.cells = [[(0x20, False)] * COLS for _ in range(ROWS)]
        self.attr = [NORMAL] * ROWS
        self.row = self.col = 0
        self.wrap = False
        self.rev = False
        self.gfx = False
        self.saved = (0, 0, False)
        self.state = "normal"
        self.params = [0]
        self.priv = False

    # -- primitives ------------------------------------------------------------
    def put(self, c):
        if self.wrap:
            self.col = 0
            self.wrap = False
            self.line_feed()
        if self.gfx and 0x5F <= c <= 0x7E:
            c -= 0x5F
        self.cells[self.row][self.col] = (c, self.rev)
        if self.col == COLS - 1:
            self.wrap = True
        else:
            self.col += 1

    def line_feed(self):
        if self.row == ROWS - 1:
            del self.cells[0]
            del self.attr[0]
            self.cells.append([(0x20, False)] * COLS)
            self.attr.append(NORMAL)
        else:
            self.row += 1

    def erase(self, r0, c0, r1, c1):
        """Cells from (r0, c0) to (r1, c1) inclusive, in reading order."""
        for r in range(r0, r1 + 1):
            a = c0 if r == r0 else 0
            b = c1 if r == r1 else COLS - 1
            for c in range(a, b + 1):
                self.cells[r][c] = (0x20, False)
            if a == 0 and b == COLS - 1:
                self.attr[r] = NORMAL

    # -- input -----------------------------------------------------------------
    def feed(self, data):
        for b in data:
            self.byte(b & 0x7F)

    def byte(self, c):
        s = self.state
        if s == "tek":
            if c == 0x18:
                self.state = "normal"
            return
        if s == "esc":
            self.state = "normal"
            if c == ord("["):
                self.state, self.params, self.priv = "csi", [0], False
            elif c == ord("#"):
                self.state = "hash"
            elif c == ord("("):
                self.state = "g0"
            elif c == ord(")"):
                self.state = "g1"
            elif c == ord("7"):
                self.saved = (self.row, self.col, self.rev)
            elif c == ord("8"):
                self.row, self.col, self.rev = self.saved
                self.wrap = False
            elif c == ord("D"):
                self.wrap = False
                self.line_feed()
            elif c == ord("E"):
                self.wrap = False
                self.col = 0
                self.line_feed()
            elif c == ord("M"):
                self.wrap = False
                if self.row > 0:
                    self.row -= 1
            elif c == ord("c"):
                self.reset()
            return
        if s == "hash":
            self.state = "normal"
            a = {ord("3"): DH_TOP, ord("4"): DH_BOTTOM, ord("6"): DW, ord("5"): NORMAL}.get(c)
            if a is not None:
                self.attr[self.row] = a
            return
        if s in ("g0", "g1"):
            self.state = "normal"
            if s == "g0":
                self.gfx = c == ord("0")
            return
        if s == "csi":
            if ord("0") <= c <= ord("9"):
                self.params[-1] = min(255, self.params[-1] * 10 + c - ord("0"))
            elif c == ord(";"):
                if len(self.params) < 4:
                    self.params.append(0)
            elif c == ord("?"):
                self.priv = True
            elif 0x40 <= c <= 0x7E:
                self.state = "normal"
                self.csi(chr(c))
            return
        # normal
        if 0x20 <= c <= 0x7E:
            self.put(c)
        elif c == 0x0D:
            self.col = 0
            self.wrap = False
        elif c in (0x0A, 0x0B, 0x0C):
            self.wrap = False
            self.line_feed()
        elif c == 0x08:
            self.wrap = False
            if self.col:
                self.col -= 1
        elif c == 0x09:
            self.wrap = False
            self.col = min(COLS - 1, (self.col | 7) + 1)
        elif c == 0x1B:
            self.state = "esc"
        elif c == 0x1D:
            self.state = "tek"

    def csi(self, f):
        p = self.params
        p1 = p[0] if p[0] else 1
        self.wrap = False
        if self.priv:
            return
        if f in "Hf":
            self.row = min(ROWS - 1, max(1, p[0]) - 1)
            self.col = min(COLS - 1, max(1, p[1] if len(p) > 1 else 1) - 1)
        elif f == "A":
            self.row = max(0, self.row - p1)
        elif f == "B":
            self.row = min(ROWS - 1, self.row + p1)
        elif f == "C":
            self.col = min(COLS - 1, self.col + p1)
        elif f == "D":
            self.col = max(0, self.col - p1)
        elif f == "J":
            if p[0] == 0:
                self.erase(self.row, self.col, ROWS - 1, COLS - 1)
            elif p[0] == 1:
                self.erase(0, 0, self.row, self.col)
            elif p[0] == 2:
                self.erase(0, 0, ROWS - 1, COLS - 1)
        elif f == "K":
            if p[0] == 0:
                self.erase(self.row, self.col, self.row, COLS - 1)
            elif p[0] == 1:
                self.erase(self.row, 0, self.row, self.col)
            elif p[0] == 2:
                self.erase(self.row, 0, self.row, COLS - 1)
        elif f == "m":
            for v in p:
                if v == 0:
                    self.rev = False
                elif v == 7:
                    self.rev = True

    # -- output ----------------------------------------------------------------
    def text(self):
        """The screen as 24 lines (line-drawing glyphs as their ASCII codes)."""
        out = []
        for r in range(ROWS):
            s = "".join(chr(c + 0x5F) if c < 0x20 else chr(c) for c, _ in self.cells[r])
            out.append(s.rstrip())
        return out

    def render(self):
        """The terminal area as term_display draws it: 640 x 384 bytes, 0 or 1."""
        from tools.gen_font import glyphs
        font = glyphs()
        px = bytearray(640 * 384)
        for r in range(ROWS):
            a = self.attr[r]
            for y in range(16):
                if a == DH_TOP:
                    gl = y >> 2
                elif a == DH_BOTTOM:
                    gl = 4 + (y >> 2)
                else:
                    gl = y >> 1
                base = (16 * r + y) * 640
                for x in range(640):
                    if a == NORMAL:
                        c, bit = x >> 3, x & 7
                    else:
                        c, bit = x >> 4, (x >> 1) & 7
                    ch, rev = self.cells[r][c]
                    on = (font[ch & 0x7F][gl] >> bit) & 1
                    px[base + x] = on ^ rev
        return bytes(px)


def main():
    t = Terminal()
    t.feed(open(sys.argv[1], "rb").read())
    for ln in t.text():
        print(ln)


if __name__ == "__main__":
    main()
