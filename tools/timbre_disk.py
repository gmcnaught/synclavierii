#!/usr/bin/env python3
"""Make a timbre library disk: a W1: image with one sub-catalog per timbre
library, each holding that library's .NEWDATA (8 banks of 8 timbres).

    timbre_disk.py OUT.IMG FILE.stmb [NAME=FILE.stmb ...] [--mb N]
        [--seq SUBCAT:N=FILE.sseq ...] [--samples DIR [--all-sounds]]

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

--seq puts sequence files in a sub-catalog of their own (e.g. DEMOS:0=
Liszt.sseq DEMOS:1=chorale.sseq): .SQ0DATA-.SQ7DATA, type 4. The panel's
SEQUENCE + button N recalls .SQnDATA from the current catalog first, then
the system catalog (SYNRSOU/05-BUTT/175-PRF5 SEQUENCER.RECALL.BUTTON), so
with W1:DEMOS the current catalog the eight buttons play the demos.
tools/seq_record.py records them.

--samples DIR adds the Original NED Sample/Patch Libraries
(tools/sample_library.py): 18 sub-catalogs (PIANO1, BRASS1, ..., SYNTH2),
each a .NEWDATA of up to 8 banks and the sound files (type 5) its timbres
play, in large (type 7, 128-entry) sub-catalogs where more than 31 files;
--all-sounds also the sound files no timbre uses (SOUNDS1, ...). SYN-5.3
finds a patch's sound file through its W0:/W1: sound-file cache. Images
over 32 MB use the catalog's high sector bits (tools/ned_disk.py) and need
the core's 24-bit SCSI block addresses (hdl/core/sd_floppy.sv).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.ned_disk import SECTOR_WORDS, add_file, blank_disk  # noqa: E402

SUBCAT_TYPE = 6          # t#subc: 256-word directory (XPL/CATCODE:834), 32 entries
LARGE_SUBCAT_TYPE = 7    # t#lsubc: 1024-word directory, 128 entries
SUBCAT_ENTRIES, LARGE_SUBCAT_ENTRIES = 32, 128
SOUND_FILE_TYPE = 5      # t#sound
NEWDATA_TYPE = 3         # as tools/w0_image.py writes W0:.NEWDATA
SEQUENCE_TYPE = 4        # .SQnDATA (as on NED's W0 demo files)
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


def make(libraries, mb=None, sequences=None, samples=None):
    """Image bytes holding `libraries` [(name, .NEWDATA bytes)],
    `samples` [(name, .NEWDATA bytes or None, [(sound name, bytes)])]
    (tools/sample_library.py) and `sequences` {sub-catalog name: {n:
    .SQnDATA bytes}}, one sub-catalog each, in that order."""
    sequences = sequences or {}
    samples = samples or []
    subcats = []                                            # (name, [(file, data, type)])
    for name, data in libraries:
        if len(data) % (2 * SECTOR_WORDS) or len(data) // (2 * SECTOR_WORDS) < MIN_SECTORS:
            raise ValueError("%s: .NEWDATA must be whole sectors, %d at least" % (name, MIN_SECTORS))
        subcats.append((name, [(".NEWDATA", data, NEWDATA_TYPE)]))
    for name, data, sounds in samples:
        files = [(".NEWDATA", data, NEWDATA_TYPE)] if data else []
        files += [(n, d, SOUND_FILE_TYPE) for n, d in sounds]
        subcats.append((name, files))
    for name, files in sequences.items():
        for n, data in files.items():
            if not 0 <= n <= 7 or not data or len(data) % 2:
                raise ValueError("%s:%s: slots are 0-7, files whole words" % (name, n))
        subcats.append((name, [(".SQ%dDATA" % n, files[n], SEQUENCE_TYPE) for n in sorted(files)]))
    names = [n for n, _f in subcats]
    if len(set(names)) != len(names):
        raise ValueError("duplicate sub-catalog names: %s" % names)
    if len(names) > 4 * SECTOR_WORDS // 8:
        raise ValueError("at most 128 sub-catalogs (the root catalog)")
    layout, need = [], 4                                    # root catalog
    for name, files in subcats:
        if not 1 <= len(name) <= 8:
            raise ValueError("%s: a name is 1-8 characters" % name)
        if len(files) > LARGE_SUBCAT_ENTRIES:
            raise ValueError("%s: %d files, a sub-catalog holds %d" % (name, len(files), LARGE_SUBCAT_ENTRIES))
        typ, cat = (SUBCAT_TYPE, 1) if len(files) <= SUBCAT_ENTRIES else (LARGE_SUBCAT_TYPE, 4)
        sectors = cat + sum(-(-len(d) // (2 * SECTOR_WORDS)) for _n, d, _t in files)
        layout.append((name, files, typ, sectors))
        need += sectors
    mb = mb or max(1, -(-need * 2 * SECTOR_WORDS // (1 << 20)))
    disk = blank_disk(mb)
    for name, files, typ, sectors in layout:
        add_file(disk, name, bytes(sectors * 2 * SECTOR_WORDS), typ=typ)
        for fname, data, ftyp in files:
            add_file(disk, "%s/%s" % (name, fname), data, typ=ftyp)
    return disk


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="W1 image to write")
    ap.add_argument("libraries", nargs="*", metavar="[NAME=]FILE.stmb")
    ap.add_argument("--mb", type=int, help="image size in MB (default: what the libraries need)")
    ap.add_argument("--seq", action="append", default=[], metavar="SUBCAT:N=FILE.sseq",
                    help="a sequence as .SQnDATA in sub-catalog SUBCAT (repeatable)")
    ap.add_argument("--samples", metavar="DIR",
                    help="the Original NED Sample/Patch Libraries folder (tools/sample_library.py)")
    ap.add_argument("--all-sounds", action="store_true",
                    help="with --samples: also the sound files no timbre uses (SOUNDS1, ...)")
    a = ap.parse_args(argv)
    seqs = {}
    for arg in a.seq:
        where, sep, path = arg.partition("=")
        sub, sep2, n = where.rpartition(":")
        if not (sep and sep2 and n.isdigit()):
            ap.error("--seq wants SUBCAT:N=FILE, e.g. DEMOS:1=chorale.sseq")
        seqs.setdefault(sub.upper(), {})[int(n)] = open(path, "rb").read()
    if not a.libraries and not seqs and not a.samples:
        ap.error("nothing to put on the disk")
    samples = []
    if a.samples:
        from tools.sample_library import caf_sound, libraries as sample_libraries
        libs_s, cafs, missing = sample_libraries(a.samples, a.all_sounds)
        for s, where in sorted(missing.items()):
            print("missing sound file %s (%s)" % (s, ", ".join(sorted(set(where)))))
        conv = {}
        for lib in libs_s:
            for s in lib.sounds:
                if s not in conv:
                    conv[s] = caf_sound(open(cafs[s], "rb").read())
            samples.append((lib.name, lib.newdata, [(s, conv[s]) for s in lib.sounds]))
    libs = []
    for arg in a.libraries:
        name, sep, path = arg.partition("=")
        if not sep:
            name, path = short_name(arg), arg
        libs.append((name.upper(), open(path, "rb").read()))
    disk = make(libs, a.mb, seqs, samples)
    open(a.out, "wb").write(disk)
    for name, data in libs:
        print("W1:%-8s .NEWDATA %d sectors" % (name, len(data) // (2 * SECTOR_WORDS)))
    for name, data, sounds in samples:
        print("W1:%-8s %s%d sound files, %d sectors" % (
            name, ".NEWDATA, " if data else "", len(sounds),
            sum(len(d) for _n, d in sounds) // (2 * SECTOR_WORDS)))
    for name, files in seqs.items():
        for n in sorted(files):
            print("W1:%-8s .SQ%dDATA %d sectors" % (name, n, -(-len(files[n]) // (2 * SECTOR_WORDS))))
    print("%s: %d MB, %d libraries, %d sample sub-catalogs, %d sequences" % (
        a.out, len(disk) >> 20, len(libs), len(samples), sum(len(f) for f in seqs.values())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
