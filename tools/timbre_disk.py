#!/usr/bin/env python3
"""Make a timbre library disk: a W1: image with one sub-catalog per timbre
library, each holding that library's .NEWDATA (8 banks of 8 timbres).

    timbre_disk.py OUT.IMG FILE.stmb [NAME=FILE.stmb ...] [--mb N]

SYN-5.3 looks for .NEWDATA in the current catalog first and only then in
the system catalog (SYNRSOU/11-TIMB/162-TMB2 FIND.NEW.BANK), and its Timbre
Directory reads .NEWDATA from any device or the current catalog
(SYNSOU/DIRMOD/570-DIRS, 575-TIMB). So, as with NED's timbre floppies, make
a library the current catalog (Subcatalog Directory, or ENTER W1:NAME in
MONITOR) and the panel's BANK and ENTRY buttons play from it; W0: needs no
rebuild to add libraries.

A sub-catalog's name is NAME (up to 8 characters) or derived from the file
name: System-Disk -> SYSDISK, Timbre-Disk-3 -> TIMBDSK3, Resynth-Library-2
-> RESYNTH2, Test-Timbres -> TESTTIMB, others the first 8 letters and digits.
Each is a small (type 6, 32-entry) sub-catalog of 1 catalog sector plus the
.NEWDATA file. Mount the image as W1 (S4) with a state image made with
tools/w0_image.py --w1. Converted libraries come from tools/stmb.py convert;
none are in the repository.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.ned_disk import SECTOR_WORDS, add_file, blank_disk  # noqa: E402

SUBCAT_TYPE = 6          # t#subc: 256-word directory (XPL/CATCODE:834)
NEWDATA_TYPE = 3         # as tools/w0_image.py writes W0:.NEWDATA
MIN_SECTORS = 192        # SYN-5.3: 24 sectors a bank at least (FIND.NEW.BANK)


def short_name(path):
    """The sub-catalog name for a library file."""
    base = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r"(?i)system[-_ ]?disk$", base)
    if m:
        return "SYSDISK"
    m = re.match(r"(?i)timbre[-_ ]?disk[-_ ]?(\d+)$", base)
    if m:
        return "TIMBDSK" + m.group(1)
    m = re.match(r"(?i)resynth[-_ ]?library[-_ ]?(\d+)$", base)
    if m:
        return "RESYNTH" + m.group(1)
    if re.match(r"(?i)test[-_ ]?timbres$", base):
        return "TESTTIMB"
    return (re.sub(r"[^A-Za-z0-9]", "", base).upper() or "LIBRARY")[:8]


def make(libraries, mb=None):
    """Image bytes holding `libraries` [(name, .NEWDATA bytes)]."""
    names = [n for n, _d in libraries]
    if len(set(names)) != len(names):
        raise ValueError("duplicate sub-catalog names: %s" % names)
    if len(libraries) > 4 * SECTOR_WORDS // 8:
        raise ValueError("at most 128 libraries (the root catalog)")
    need = 4                                                # root catalog
    for name, data in libraries:
        if not 1 <= len(name) <= 8:
            raise ValueError("%s: a name is 1-8 characters" % name)
        if len(data) % (2 * SECTOR_WORDS) or len(data) // (2 * SECTOR_WORDS) < MIN_SECTORS:
            raise ValueError("%s: .NEWDATA must be whole sectors, %d at least" % (name, MIN_SECTORS))
        need += 1 + len(data) // (2 * SECTOR_WORDS)
    mb = mb or max(1, -(-need * 2 * SECTOR_WORDS // (1 << 20)))
    disk = blank_disk(mb)
    for name, data in libraries:
        sectors = 1 + len(data) // (2 * SECTOR_WORDS)
        add_file(disk, name, bytes(sectors * 2 * SECTOR_WORDS), typ=SUBCAT_TYPE)
        add_file(disk, name + "/.NEWDATA", data, typ=NEWDATA_TYPE)
    return disk


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="W1 image to write")
    ap.add_argument("libraries", nargs="+", metavar="[NAME=]FILE.stmb")
    ap.add_argument("--mb", type=int, help="image size in MB (default: what the libraries need)")
    a = ap.parse_args(argv)
    libs = []
    for arg in a.libraries:
        name, sep, path = arg.partition("=")
        if not sep:
            name, path = short_name(arg), arg
        libs.append((name.upper(), open(path, "rb").read()))
    disk = make(libs, a.mb)
    open(a.out, "wb").write(disk)
    for name, data in libs:
        print("W1:%-8s .NEWDATA %d sectors" % (name, len(data) // (2 * SECTOR_WORDS)))
    print("%s: %d MB, %d libraries" % (a.out, len(disk) >> 20, len(libs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
