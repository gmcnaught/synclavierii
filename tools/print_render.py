#!/usr/bin/env python3
"""Render what the Synclavier printed on its D40 printer port (an IDS Paper
Tiger / Prism, the printer SYN-5.3's screen hardcopy is written for) as
page images: docs/devices/d40-printer.md.

    print_render.py CAPTURE OUT.png [--pdf OUT.pdf] [--raw]
    print_render.py --blank FILE [--mb N]

CAPTURE is the core's capture file (SD slot S6; header below) or, with
--raw, the bytes alone (sim/devices/printer.py Printer.out). Each page goes
to OUT.png, or OUT-1.png, OUT-2.png, ... when there are several; --pdf also
writes them as one PDF. --blank makes an empty capture file of N MB
(default 4) to mount in S6.

Capture file: 512-byte blocks. Block 0 is the header: bytes 0-7
"SYNCPRNT", 8-9 version (1, big-endian), 10-13 the number of bytes printed
(big-endian), the rest 0. The bytes follow from block 1, in order.

Printer model (IDS Paper Tiger / Prism, as SYN-5.3 drives it; [INF] from
the bytes D40SOU sends, the printer's manual is not in the NED source):
  text      printable bytes at 10 characters per inch, 6 lines per inch;
            CR to column 0, LF next line, FF next page, BS back one column;
            other control bytes (DC4 after each line of SCREEN_DUMP) ignored.
  ETX       enters graphics; in graphics each byte (bits 0-6) is a column of
            7 dots, bit 0 at the top, 84 dots per inch across and down;
            ETX ETX a data byte 3, ETX SO a graphics line feed (7 dots,
            back to the left margin), ETX FF form feed, ETX STX back to text.
Pages are 8.5 x 11 inches at 84 pixels per inch (714 x 924), 0.25 inch
margins; the text cell is 8 x 14 pixels (the core's 8 x 8 font, rows 1.5
times as in tools/vt100.py's graphics text).
"""
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MAGIC = b"SYNCPRNT"
VERSION = 1
BLOCK = 512
DPI = 84
PAGE_W, PAGE_H = 714, 924          # 8.5 x 11 inches
MARGIN = 21
CELL_W, CELL_H = 8, 14             # 10.5 cpi (nearest to 10 with the 8-pixel font), 6 lpi
ETX, STX, SO, FF = 3, 2, 14, 12


def header(count):
    """Block 0 of a capture file holding `count` bytes."""
    return (MAGIC + struct.pack(">HI", VERSION, count)).ljust(BLOCK, b"\0")


def read_capture(data):
    """The printed bytes of a capture file (raw bytes if it has no header)."""
    if data[:8] != MAGIC:
        raise ValueError("not a capture file (no SYNCPRNT header); use --raw for bytes alone")
    count = struct.unpack_from(">I", data, 10)[0]
    return bytes(data[BLOCK:BLOCK + count])


class Page:
    def __init__(self):
        self.w, self.h = PAGE_W, PAGE_H
        self.px = bytearray(self.w * self.h)

    def set(self, x, y):
        if x >= self.w or y >= self.h:
            self.grow(x + 1, y + 1)
        self.px[y * self.w + x] = 1

    def grow(self, w, h):
        """Content beyond the paper (a line too long): widen/lengthen."""
        w, h = max(w, self.w), max(h, self.h)
        px = bytearray(w * h)
        for y in range(self.h):
            px[y * w:y * w + self.w] = self.px[y * self.w:(y + 1) * self.w]
        self.w, self.h, self.px = w, h, px


def render(data):
    """Pages (Page) for a printed byte stream."""
    from tools.gen_font import glyphs
    font = glyphs()
    pages = [Page()]
    x, y = MARGIN, MARGIN              # top-left of the current text cell / graphics column
    graphics = esc = False
    used = False                       # anything on the current page

    def new_page():
        nonlocal x, y, used
        pages.append(Page())
        x, y, used = MARGIN, MARGIN, False

    for b in data:
        if graphics:
            if esc:
                esc = False
                if b == ETX:
                    pass                           # a data byte 3, below
                elif b == STX:
                    graphics = False
                    continue
                elif b == SO:
                    x, y = MARGIN, y + 7
                    continue
                elif b == FF:
                    if used:
                        new_page()
                    continue
                else:
                    continue                       # other ETX commands: ignored
            elif b == ETX:
                esc = True
                continue
            for i in range(7):
                if b >> i & 1:
                    pages[-1].set(x, y + i)
                    used = True
            x += 1
            continue
        b &= 0x7F
        if b == ETX:
            graphics = True
        elif b == 0x0D:
            x = MARGIN
        elif b == 0x0A:
            y += CELL_H
        elif b == FF:
            if used:
                new_page()
            else:
                x, y = MARGIN, MARGIN
        elif b == 0x08:
            x = max(MARGIN, x - CELL_W)
        elif 0x20 <= b < 0x7F:
            g = font[b]
            for line in range(1, 13):
                bits = g[(line - 1) * 2 // 3]
                for col in range(8):
                    if bits >> col & 1:
                        pages[-1].set(x + col, y + line)
            if b != 0x20:
                used = True
            x += CELL_W
    if not used and len(pages) > 1:
        pages.pop()
    return pages


def png(page):
    """A 1-bit greyscale PNG of a page (black ink on white)."""
    rows = bytearray()
    stride = (page.w + 7) // 8
    for y in range(page.h):
        rows.append(0)                             # filter: none
        line = page.px[y * page.w:(y + 1) * page.w]
        packed = bytearray(stride)
        for x in range(page.w):
            if not line[x]:
                packed[x >> 3] |= 0x80 >> (x & 7)  # 1 = white
        rows += packed

    def chunk(kind, body):
        c = kind + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", page.w, page.h, 1, 0, 0, 0, 0))
            + chunk(b"pHYs", struct.pack(">IIB", round(DPI / 0.0254), round(DPI / 0.0254), 1))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def pdf(pages):
    """A PDF with one page per Page, each the page image at 84 dpi."""
    objs = []                                      # object bodies, numbered from 1
    kids = []
    for p in pages:
        stride = (p.w + 7) // 8
        img = bytearray()
        for y in range(p.h):
            packed = bytearray(stride)
            for x in range(p.w):
                if p.px[y * p.w + x]:
                    packed[x >> 3] |= 0x80 >> (x & 7)   # 1 = ink (Decode below)
            img += packed
        data = zlib.compress(bytes(img), 9)
        w_pt, h_pt = p.w * 72 / DPI, p.h * 72 / DPI
        objs.append(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
                    b"/BitsPerComponent 1 /Decode [1 0] /Filter /FlateDecode /Length %d >>\nstream\n"
                    % (p.w, p.h, len(data)) + data + b"\nendstream")
        im = len(objs)
        content = b"q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q" % (w_pt, h_pt)
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        ct = len(objs)
        objs.append(b"<< /Type /Page /Parent PAGES /MediaBox [0 0 %.2f %.2f] "
                    b"/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
                    % (w_pt, h_pt, im, ct))
        kids.append(len(objs))
    objs.append(b"<< /Type /Pages /Kids [%s] /Count %d >>"
                % (b" ".join(b"%d 0 R" % k for k in kids), len(kids)))
    pages_ref = b"%d 0 R" % len(objs)
    objs = [o.replace(b"PAGES", pages_ref) for o in objs]
    objs.append(b"<< /Type /Catalog /Pages %s >>" % pages_ref)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, len(objs), xref)
    return bytes(out)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("capture", nargs="?")
    ap.add_argument("out", nargs="?", help="PNG file (several pages: OUT-1.png, ...)")
    ap.add_argument("--pdf", help="also write the pages as one PDF")
    ap.add_argument("--raw", action="store_true", help="CAPTURE is the printed bytes alone")
    ap.add_argument("--blank", metavar="FILE", help="write an empty capture file and stop")
    ap.add_argument("--mb", type=int, default=4, help="--blank: file size in MB")
    a = ap.parse_args(argv)
    if a.blank:
        with open(a.blank, "wb") as f:
            f.write(header(0))
            f.truncate(a.mb << 20)
        print("%s: empty capture file, %d MB (%d bytes of printing)"
              % (a.blank, a.mb, (a.mb << 20) - BLOCK))
        return 0
    if not a.capture or not a.out:
        ap.error("CAPTURE and OUT are needed (or --blank FILE)")
    data = open(a.capture, "rb").read()
    if not a.raw:
        data = read_capture(data)
    pages = render(data)
    base, ext = os.path.splitext(a.out)
    names = [a.out] if len(pages) == 1 else ["%s-%d%s" % (base, i + 1, ext or ".png")
                                             for i in range(len(pages))]
    for p, n in zip(pages, names):
        open(n, "wb").write(png(p))
    if a.pdf:
        open(a.pdf, "wb").write(pdf(pages))
    print("%d bytes, %d page(s): %s%s" % (len(data), len(pages), ", ".join(names),
                                          " and " + a.pdf if a.pdf else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
