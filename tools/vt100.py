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
  GS          Tektronix graphics: everything up to CAN is skipped (in
              VT640 mode, Terminal(vt640=True), it is drawn: below).
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
  ESC c       reset: clear, home, normal, numeric keypad
  ESC = / >   keypad application / numeric mode (`keypad`: what the
              keyboard sends for keypad Enter, hdl/core/ps2_ascii.sv)
  ESC FF and other ESC c: ignored

Picture (640 x 384 terminal area): row r is lines 16r-16r+15; normal rows
show columns 0-79 at 8 pixels, each font row twice; double-width rows show
columns 0-39 at 16 pixels (each pixel twice); double-height rows also
stretch the top (rows 0-3) or bottom (rows 4-7) half of the glyph over the
16 lines (each font row 4 times). Reverse cells are inverted. The cursor is
not drawn (it blinks).

VT640 mode (docs/devices/vt640-graphics-terminal.md; SYN-5.3 configured
for a VT640): a 640 x 480 x 1 graphics plane, y up, drawn by a Tektronix
4010 subset, ORed with the text plane on a 640 x 480 terminal area.
  GS          vector mode; the next address moves, later ones draw lines
  FS          point mode; each address plots a point
  US          (in vector/point mode) alpha mode at the graphics position
  CAN         back to text
  addresses   HiY 040-077, LoY 0140-0177 (DEL too), HiX 040-077 after a
              LoY, LoX 0100-0137 ends one; Tek (x, y) 0-1023 x 0-779 ->
              VT640 pixel x = (x*640 + 512) >> 10, y = (min(y,779)*630 + 640) >> 10
  ESC FF      clear the graphics plane, pen up (in any graphics mode)
  ESC / n d   data level: 0 set, 1 clear, 2 complement (XOR)
  ESC 0-3, ESC 8-;   character size: accepted, no effect [CHOICE: the VT640
              is a Tek 4010-class terminal with one size; SYN-5.3's size-1
              title at y = 470 only fits at size 0]
  ESC ` a-e x line type (drawn solid); ESC | c c, ESC backslash c, ESC ! c...:
              ignored; other ESC c: ignored
  ESC " 0 ; y ; n c   read back n 5-pixel groups of graphics line y (y up,
              0-479) from the left (SYN-5.3's screen hardcopy, D40SOU
              read_screen; docs/devices/d40-printer.md): the reply
              (readback_reply) goes to `reply` (Terminal(reply=callable));
              other ESC " ... finals are ignored
  alpha       printable: an 8 x 14 cell whose lower-left corner is the
              graphics position; the 5 x 7 dot-matrix glyph
              (tools/gen_font.py glyphs610, X.Org 6x10) at 1:1 on columns
              1-5, font row r (1-9) on line 8 - r above the position
              (capitals lines 1-7, descenders lines 0 and -1), then x += 8; BS x -= 8, CR x = 0, LF y -= 14; data level
              applies.
Lines (Bresenham, both end points) and points use the data level; with
XOR a shared end point of two vectors is flipped twice [CHOICE].
Text plane in VT640 mode: row r on lines 20r-20r+19, the VT220 font
(tools/gen_font.py glyphs_glass, Glass TTY: 10 rows) doubled; column c
from pixel 8 + ceil(7.5c), 8 pixels wide for even c and 7 for odd (font
column 7 dropped); double-width columns 15 pixels from 8 + 15c; double
height: font rows 0-4 (top) or 5-9 (bottom), 4 lines each; reverse
inverts all 20 lines of the cell. (The cursor, font row 8, is not drawn
here: term_display.sv blinks it.)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROWS, COLS = 24, 80
NORMAL, DH_TOP, DH_BOTTOM, DW = 0, 1, 2, 3


GW, GH = 640, 480


def tek_to_pixel(xt, yt):
    """Tek 4010 address -> VT640 pixel (the exact inverse of SYN-5.3's
    x_tek = floor(x*1023/639), y_tek = floor(y*779/479))."""
    return (xt * 640 + 512) >> 10, (min(yt, 779) * 630 + 640) >> 10


def readback_reply(g, y, groups):
    """The VT640 read-back reply for graphics line y (0 = bottom) of plane g
    (row 0 = top): `groups` groups of 5 pixels from x = 0, each a value
    with bit 4 = its leftmost pixel; run-length coded as SYN-5.3 decodes it
    (D40SOU read_screen): a run of 0 -> "$" n, of 037 -> "%" n, of another
    value v, 3 or more long -> "&" v n, else single bytes v; v and n are
    sent as 0100 | value (n 1..63); then CR. [CHOICE: the real VT640's reply
    format is not documented in the NED source beyond what it decodes]"""
    row = GH - 1 - y
    vals = []
    for k in range(groups):
        v = 0
        for i in range(5):
            x = 5 * k + i
            on = 0 <= row < GH and x < GW and g[row * GW + x]
            v = v << 1 | (1 if on else 0)
        vals.append(v)
    out = bytearray()
    k = 0
    while k < len(vals):
        v, n = vals[k], 1
        while k + n < len(vals) and vals[k + n] == v and n < 63:
            n += 1
        if v == 0:
            out += bytes((0o44, 0o100 | n))
        elif v == 0o37:
            out += bytes((0o45, 0o100 | n))
        elif n >= 3:
            out += bytes((0o46, 0o100 | v, 0o100 | n))
        else:
            out += bytes([0o100 | v] * n)
        k += n
    return bytes(out + b"\r")


class Terminal:
    def __init__(self, vt640=False, reply=None):
        self.vt640 = vt640
        self.reply = reply                   # callable(bytes): read-back replies
        self.g = bytearray(GW * GH)          # graphics plane, row 0 = top (y = 479)
        self.gmode = None                    # None (text), "vector", "point", "alpha"
        self.pen = False
        self.gx = self.gy = 0
        self.hiy = self.loy = self.hix = 0
        self.after_loy = False
        self.level = 0
        self.size = 0
        self.gesc = None                     # graphics ESC sub-state
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
        self.keypad = False

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
        if self.vt640 and (self.gmode is not None or c in (0x1C, 0x1D)) \
                and self.state in ("normal", "tek"):
            self.tek(c)
            return
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
            elif c == ord("="):
                self.keypad = True
            elif c == ord(">"):
                self.keypad = False
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
    # -- VT640 graphics ----------------------------------------------------------
    def plot(self, x, y):
        if 0 <= x < GW and 0 <= y < GH:
            i = (GH - 1 - y) * GW + x
            self.g[i] = 1 if self.level == 0 else 0 if self.level == 1 else self.g[i] ^ 1

    def line(self, x0, y0, x1, y1):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.plot(x0, y0)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def glyph(self, ch):
        """A graphics-mode (alpha) character: a 5 x 7 dot matrix at 1:1
        [CHOICE: SYN-5.3 draws a note head as O (BS #) from (X-3, Y-4) with
        the stem at X+-3 (MNOTMOD/PICSFNCS.xpl NOTE, PLOTFNCS.xpl), so its
        O is 7 rows tall from line 1 and centred 3 columns in]."""
        from tools.gen_font import glyphs610
        if not hasattr(self, "_font610"):
            self._font610 = glyphs610()
        g = self._font610[ch]
        for r in range(1, 10):                 # row 1 = capital top, 7 = baseline row
            for col in range(5):
                if g[r] >> col & 1:
                    self.plot(self.gx + 1 + col, self.gy + 8 - r)

    def tek(self, c):
        if self.gesc is not None:                  # ESC sequences in graphics
            g = self.gesc
            if g == "esc":
                if c == 0x0C:
                    self.g[:] = bytes(GW * GH)
                    self.pen = False
                    self.gesc = None
                elif c == ord("/"):
                    self.gesc, self.num = "slash", 0
                elif c == ord("|"):
                    self.gesc = 2                  # two bytes to skip
                elif c == ord("\\"):
                    self.gesc = 1
                elif c == ord('"'):
                    self.gesc, self.rb = "readback", [0]
                else:
                    self.gesc = None
            elif g == "readback":                  # ESC " p ; p ; p final
                if ord("0") <= c <= ord("9"):
                    self.rb[-1] = min(9999, self.rb[-1] * 10 + c - ord("0"))
                elif c == ord(";"):
                    if len(self.rb) < 3:
                        self.rb.append(0)
                else:
                    self.gesc = None
                    if c == ord("c") and len(self.rb) == 3 and self.reply:
                        self.reply(readback_reply(self.g, self.rb[1], min(self.rb[2], 128)))
            elif g == "slash":
                if ord("0") <= c <= ord("9"):
                    self.num = min(9, self.num * 10 + c - ord("0"))
                elif c == ord("d"):
                    self.level = self.num if self.num <= 2 else 0
                    self.gesc = None
                elif c == ord(";"):
                    self.num = 0
                else:
                    self.gesc = None               # e.g. /1;1a: line type, ignored
            else:
                self.gesc = None if g == 1 else g - 1
            return
        if c == 0x1D:                              # GS
            self.gmode, self.pen, self.after_loy = "vector", False, False
        elif c == 0x1C:                            # FS
            self.gmode, self.after_loy = "point", False
        elif c == 0x18:                            # CAN
            self.gmode = None
            self.state = "normal"
        elif c == 0x1B:
            self.gesc = "esc"
        elif c == 0x1F:                            # US
            if self.gmode in ("vector", "point"):
                self.gmode = "alpha"
        elif self.gmode == "alpha":
            k = self.size + 1
            if 0x20 <= c <= 0x7E:
                self.glyph(c)
                self.gx += 8 * k
            elif c == 0x08:
                self.gx -= 8 * k
            elif c == 0x0D:
                self.gx = 0
            elif c == 0x0A:
                self.gy -= 14 * k
        elif c >= 0x20:                            # an address byte
            if 0x60 <= c:                          # LoY (DEL included)
                self.loy, self.after_loy = c & 31, True
            elif 0x20 <= c < 0x40:                 # HiY, or HiX right after a LoY
                if self.after_loy:
                    self.hix = c & 31
                else:
                    self.hiy = c & 31
                self.after_loy = False
            else:                                  # LoX: the address is complete
                x, y = tek_to_pixel(self.hix << 5 | (c & 31), self.hiy << 5 | self.loy)
                self.after_loy = False
                if self.gmode == "vector":
                    if self.pen:
                        self.line(self.gx, self.gy, x, y)
                    self.pen = True
                else:
                    self.plot(x, y)
                self.gx, self.gy = x, y

    def text(self):
        """The screen as 24 lines (line-drawing glyphs as their ASCII codes)."""
        out = []
        for r in range(ROWS):
            s = "".join(chr(c + 0x5F) if c < 0x20 else chr(c) for c, _ in self.cells[r])
            out.append(s.rstrip())
        return out

    def render(self):
        """The terminal area as term_display draws it: 640 x 384 bytes, 0 or 1
        (VT640 mode: 640 x 480, text OR graphics)."""
        if self.vt640:
            return self.render640()
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


    def render640(self):
        from tools.gen_font import glyphs_glass
        font = glyphs_glass()
        px = bytearray(self.g)
        for r in range(ROWS):
            a = self.attr[r]
            for line in range(20):
                if a == DH_TOP:
                    gl = line >> 2
                elif a == DH_BOTTOM:
                    gl = 5 + (line >> 2)
                else:
                    gl = line >> 1
                base = (20 * r + line) * GW
                for x in range(8, 608):
                    o = x - 8
                    if a == NORMAL:
                        c = o * 2 // 15
                        bit = o - ((15 * c + 1) >> 1)
                    else:
                        c = o // 15
                        bit = (o - 15 * c) * 8 // 15
                        if c >= COLS // 2:
                            continue
                    ch, rev = self.cells[r][c]
                    on = 0 if bit > 7 else (font[ch & 0x7F][gl] >> bit) & 1
                    px[base + x] |= on ^ rev
        return bytes(px)


def main():
    t = Terminal()
    t.feed(open(sys.argv[1], "rb").read())
    for ln in t.text():
        print(ln)


if __name__ == "__main__":
    main()
