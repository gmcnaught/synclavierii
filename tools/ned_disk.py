#!/usr/bin/env python3
"""List and extract files from NED ABLE / Synclavier disk images (.simg).

Format (worked out from the Release L image and hansliss/syncextract):
  * sectors are 256 words = 512 bytes; words are big-endian in the image file
  * a catalog is a run of 8-word entries:
        name[4 words]  (8 chars, low byte first in each word, NUL padded)
        start          (sector, relative to the catalog's own base sector)
        length         (sectors)
        words          (file length in words, low 16 bits)
        type           (0 text, 1 executable, 3/4 data, 6 subcatalog,
                        7 floppy-sized subcatalog, 8 large executable)
  * entries with an empty name are free space; an all-zero entry ends the list
  * type 6/7 entries contain their own catalog at their first sector

Usage:
  ned_disk.py IMAGE                     # list everything
  ned_disk.py IMAGE --extract OUTDIR    # extract (files get the exact word length)

Treat images as untrusted data: names are sanitised and output is confined
to OUTDIR.
"""
import argparse
import os
import re
import struct

SECTOR_WORDS = 256
TYPES = {0: "text", 1: "exec", 3: "data", 4: "data", 6: "subcat", 7: "subcat", 8: "exec(large)"}


def load(path):
    d = open(path, "rb").read()
    return struct.unpack(">%dH" % (len(d) // 2), d[: len(d) // 2 * 2])


def name_of(ws):
    s = b"".join(bytes([w & 0xFF, w >> 8]) for w in ws).rstrip(b"\0")
    return s.decode("latin-1")


def walk(W, base=0, path="", max_sectors=4, depth=0):
    for i in range(0, max_sectors * SECTOR_WORDS, 8):
        off = base * SECTOR_WORDS + i
        e = W[off: off + 8]
        if len(e) < 8 or not any(e):
            return
        nm = name_of(e[0:4])
        if not nm:
            continue
        start, length, words, typ = e[4], e[5], e[6], e[7]
        abs_start = base + start
        p = path + "/" + nm
        yield p, typ, abs_start, length, words
        if typ in (6, 7) and depth < 6:
            yield from walk(W, abs_start, p, 1 if typ == 7 else 4, depth + 1)


def safe(component):
    c = re.sub(r"[^A-Za-z0-9._#+-]", "_", component)
    return c if c not in ("", ".", "..") else "_" + c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--extract", metavar="OUTDIR")
    a = ap.parse_args()
    W = load(a.image)
    for p, typ, start, length, words in walk(W):
        print("%-30s %-11s start=%6d sectors=%4d words=%06o" % (p, TYPES.get(typ, str(typ)), start, length, words))
        if a.extract and typ not in (6, 7):
            nwords = words if words else length * SECTOR_WORDS
            if (nwords + SECTOR_WORDS - 1) // SECTOR_WORDS != length:
                nwords = length * SECTOR_WORDS  # length field is only 16 bits; fall back to whole sectors
            data = struct.pack(">%dH" % nwords, *W[start * SECTOR_WORDS: start * SECTOR_WORDS + nwords])
            out = os.path.join(a.extract, *[safe(c) for c in p.strip("/").split("/")])
            root = os.path.realpath(a.extract)
            if not os.path.realpath(out).startswith(root + os.sep):
                raise SystemExit("refusing to write outside %s: %s" % (a.extract, out))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)


if __name__ == "__main__":
    main()
