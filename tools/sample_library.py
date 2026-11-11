#!/usr/bin/env python3
"""The Original NED Sample/Patch Libraries (synclavier.com) as W1: library
sub-catalogs: timbre banks packed into 8-bank .NEWDATA files by instrument
family, and the Synclavier³ .caf exports turned back into NED sound files.

    sample_library.py ROOT [--all-sounds] [--report FILE]

ROOT is the unpacked `Original-NED-Sample-Patch-Libraries` folder: one
folder per bank file (`*NEWDATA.stmb`, 1, 2, 3 or 8 banks), `AM-DATA` (two
FM timbres as text) and `NED_TL23` (all 2,075 sound files as .caf). Prints
the libraries that tools/timbre_disk.py --samples ROOT puts on the disk
(docs/timbre-libraries.md, "Original NED Sample/Patch Libraries on W1:").

A .caf from Synclavier³ carries the NED sound file's first three sectors
(header and symbol table) verbatim in its `SNCL` chunk, big-endian words,
and the samples as 16-bit little-endian PCM (interleaved when stereo) in
`data` after a 4-byte edit count. The NED file is those 768 words, then the
samples as big-endian words, padded with zeros to 3 + the header's total
data sectors (word 7): no resampling, loops, pitch, marks and caption as
they were. The catalog name is the .caf's name (what the timbres' patch
lists name).

A timbre names its sound files in its type-1 frames (patch list entries,
48 words; words 3-6 = the 8-character name, low byte first), without a
catalog path: SYN-5.3 finds them through its cache of every sound file on
W0: and W1: (SYNRSOU/03-PRIM/197-PAL2 FIND.SOUND), or failing that in the
current catalog (11-TIMB/198-SYN2). Each library sub-catalog therefore
holds its .NEWDATA and every sound file its timbres use (a sound shared by
two libraries is in both). --all-sounds adds the sound files no timbre
uses, in sub-catalogs SOUNDS1, SOUNDS2, ... (127 files each).

Treat the input as untrusted data: only the chunks listed are read, and
names must be NED file names (1-8 of A-Z 0-9 # - . ).
"""
import argparse
import glob
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools.stmb import (EMPTY, bank_bytes, encode_entry, parse_text,  # noqa: E402
                        read_banks, text_name)

SECTOR_WORDS = 256
HEADER_SECTORS = 3                  # header + 2 symbol-table sectors
SOUND_FILE_TYPE = 5
MAX_FILE_SECTORS = 65535            # SYN-5.3 refuses longer files (197-PAL1:378-386)
SUBCAT_FILES = 127                  # a large (type 7) sub-catalog: 128 entries, one for .NEWDATA
NAME_RE = re.compile(r"^[A-Z0-9#.\-]{1,8}$")

# Libraries by instrument family: (sub-catalog stem, bank-file prefixes).
# A family with more than 8 banks is split into STEM1, STEM2, ...
FAMILIES = [
    ("PIANO", ["PNO", "HPC"]),
    ("BRASS", ["TPT", "TBN", "FHN", "FLG"]),
    ("WINDS", ["FLT", "SSX", "TSX", "MWW"]),
    ("STRINGS", ["VLN", "ABS", "HRP", "GTR", "BJO", "EBS"]),
    ("DRUMS", ["DRM", "BDR", "SNR", "TOM", "HIH", "RID", "CRA", "SPL", "TMP", "GNG"]),
    ("PERC", ["PRC", "CBA", "CBL", "CGA", "CLV", "GUI", "RAT", "SHK", "TAM", "TMB",
              "TRI", "WBK", "XTK", "MBL", "MPC"]),
    ("MALLETS", ["MBA", "OBL", "CHI", "KBA", "STD"]),
    ("SYNTH", ["SYN", "AM-"]),
]


# ------------------------------------------------------------------ .caf
def _chunks(d):
    if d[:4] != b"caff" or struct.unpack(">H", d[4:6])[0] != 1:
        raise ValueError("not a CAF file")
    out, p = {}, 8
    while p + 12 <= len(d):
        t = d[p:p + 4].decode("latin-1")
        n = struct.unpack(">q", d[p + 4:p + 12])[0]
        if n < 0:                                   # data chunk to the end
            n = len(d) - p - 12
        if p + 12 + n > len(d):
            raise ValueError("chunk %r runs past the end" % t)
        out.setdefault(t, d[p + 12:p + 12 + n])
        p += 12 + n
    return out


def caf_sound(data):
    """NED sound file bytes (big-endian words) from Synclavier³ .caf bytes."""
    c = _chunks(data)
    for k in ("desc", "SNCL", "data"):
        if k not in c:
            raise ValueError("no %s chunk" % k)
    rate, fmt, flags, bpp, fpp, ch, bits = struct.unpack(">d4sIIIII", c["desc"][:32])
    if fmt != b"lpcm" or bits != 16 or flags & 1 or ch not in (1, 2) or bpp != 2 * ch or fpp != 1:
        raise ValueError("not 16-bit integer PCM, 1 or 2 channels")
    if len(c["SNCL"]) != HEADER_SECTORS * SECTOR_WORDS * 2:
        raise ValueError("SNCL chunk is %d bytes, not 3 sectors" % len(c["SNCL"]))
    hdr = list(struct.unpack(">%dH" % (HEADER_SECTORS * SECTOR_WORDS), c["SNCL"]))
    pcm = c["data"][4:]                             # after the edit count
    n = len(pcm) // 2
    valid = (hdr[2] << 16 | hdr[3]) * SECTOR_WORDS + hdr[4]
    if valid != n:
        raise ValueError("header has %d sample words, data %d" % (valid, n))
    if hdr[41] != (ch == 2):
        raise ValueError("header stereo flag %d, %d channels" % (hdr[41], ch))
    sectors = hdr[6] << 16 | hdr[7]
    if sectors * SECTOR_WORDS < n:
        sectors = -(-n // SECTOR_WORDS)
    if HEADER_SECTORS + sectors > MAX_FILE_SECTORS:
        raise ValueError("%d sectors: SYN-5.3 loads files under 65536" % (HEADER_SECTORS + sectors))
    order = ">" if flags & 2 == 0 else "<"         # kCAFLinearPCMFormatFlagIsLittleEndian
    samples = struct.unpack("%s%dh" % (order, n), pcm[:2 * n])
    out = c["SNCL"] + struct.pack(">%dh" % n, *samples)
    return out + bytes((HEADER_SECTORS + sectors) * SECTOR_WORDS * 2 - len(out))


# ------------------------------------------------------------- libraries
def patch_names(t):
    """Sound file names in a parsed timbre's patch lists, in order."""
    out = []
    for pt in t["partials"]:
        for f in (pt or {}).get("frames", []):
            if f[1] == 1 and len(f) >= 7:
                nm = text_name(f[3:7])
                if nm and nm not in out:
                    out.append(nm)
    return out


# Records that parse but are not timbres: TOMDTA43's bank file holds one
# timbre (TUNED TOMS), then wave-table words that read as entries 2-8
# (docs/timbre-libraries.md, "Experiment: a .stmb bank in Release L").
NOT_TIMBRES = {("TOMDTA43", 1): range(2, 9)}


def _empty(t):
    return t is None or not any(t["partials"])


def bank_sources(root):
    """[(folder, bank number in its file, [8 timbres])] in folder order;
    empty banks are left out. AM-DATA's text entries are encoded (stmb.py)."""
    out = []
    for d in sorted(glob.glob(os.path.join(root, "*", ""))):
        folder = os.path.basename(os.path.dirname(d))
        files = glob.glob(os.path.join(d, "*NEWDATA.stmb"))
        if files:
            _, _, banks = read_banks(files[0])
            for i, b in enumerate(banks):
                for e in NOT_TIMBRES.get((folder, i + 1), ()):
                    b[e - 1] = None
                if not all(_empty(t) for t in b):
                    out.append((folder, i + 1, b))
            continue
        texts = sorted(glob.glob(os.path.join(d, "[1-8][1-8]-Entry.txt")))
        banks = {}
        for f in texts:
            b, i = int(os.path.basename(f)[0]), int(os.path.basename(f)[1])
            banks.setdefault(b, [None] * 8)[i - 1] = encode_entry(parse_text(f))[0]
        for b in sorted(banks):
            out.append((folder, b, banks[b]))
    return out


def family_of(folder):
    for stem, prefixes in FAMILIES:
        if any(folder.upper().startswith(p) for p in prefixes):
            return stem
    return "OTHER"


def group_banks(sources):
    """[(sub-catalog name, [(folder, bank, timbres)])]: each family's banks
    in folder order, 8 to a library; a bank file's banks stay together when
    they fit in one library."""
    fam = {}
    for s in sources:
        fam.setdefault(family_of(s[0]), []).append(s)
    out = []
    order = [f for f, _ in FAMILIES] + ["OTHER"]
    for stem in order:
        if stem not in fam:
            continue
        libs, cur = [], []
        by_file = []
        for s in fam[stem]:
            if by_file and by_file[-1][0][0] == s[0]:
                by_file[-1].append(s)
            else:
                by_file.append([s])
        for grp in by_file:
            if len(cur) + len(grp) > 8 and len(grp) <= 8 and cur:
                libs.append(cur)
                cur = []
            for s in grp:
                if len(cur) == 8:
                    libs.append(cur)
                    cur = []
                cur.append(s)
        if cur:
            libs.append(cur)
        for i, banks in enumerate(libs):
            name = stem if len(libs) == 1 else "%s%d" % (stem, i + 1)
            if len(name) > 8:
                raise ValueError("%s: a sub-catalog name is 8 characters at most" % name)
            out.append((name, banks))
    return out


def caf_index(root):
    """{NAME: path} of the .caf sound files under ROOT."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "*", "*.caf"))):
        nm = os.path.splitext(os.path.basename(p))[0].upper()
        if not NAME_RE.match(nm):
            raise ValueError("%s: not a NED file name" % p)
        if nm in out:
            raise ValueError("%s: two sound files named %s" % (p, nm))
        out[nm] = p
    return out


class Library:
    """A W1: sub-catalog: name, .NEWDATA bytes (or None), sound file names,
    and the bank listing [(bank, folder, file bank, [timbre names])]."""

    def __init__(self, name, newdata, sounds, listing):
        self.name, self.newdata, self.sounds, self.listing = name, newdata, sounds, listing


def libraries(root, all_sounds=False):
    """(libraries, {sound name: .caf path}, missing {name: [library]})."""
    cafs = caf_index(root)
    out, used, missing = [], set(), {}
    for name, banks in group_banks(bank_sources(root)):
        sounds, listing = [], []
        for n, (folder, fb, ts) in enumerate(banks):
            listing.append((n + 1, folder, fb, [t.get("name", "") if t else "" for t in ts]))
            for t in ts:
                for s in (patch_names(t) if t else []):
                    if s not in cafs:
                        missing.setdefault(s, []).append(name)
                    elif s not in sounds:
                        sounds.append(s)
        if len(sounds) > SUBCAT_FILES:
            raise ValueError("%s: %d sound files, a sub-catalog holds %d with .NEWDATA"
                             % (name, len(sounds), SUBCAT_FILES))
        data = bank_bytes([ts for _f, _b, ts in banks])[0]
        out.append(Library(name, data, sorted(sounds), listing))
        used |= set(sounds)
    if all_sounds:
        rest = sorted(set(cafs) - used)
        for i in range(0, len(rest), SUBCAT_FILES + 1):
            out.append(Library("SOUNDS%d" % (i // (SUBCAT_FILES + 1) + 1), None,
                               rest[i:i + SUBCAT_FILES + 1], []))
    return out, cafs, missing


def report(libs, cafs):
    lines = []
    for lib in libs:
        sec = sum(-(-os.path.getsize(cafs[s]) // 512) for s in lib.sounds)   # about
        lines.append("W1:%-8s %3d sound files, about %d MB" % (lib.name, len(lib.sounds), sec >> 11))
        for n, folder, fb, names in lib.listing:
            shown = [x for x in names if x]
            lines.append("  BANK %d  %s bank %d: %s" % (n, folder, fb, ", ".join(shown)))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", help="the Original-NED-Sample-Patch-Libraries folder")
    ap.add_argument("--all-sounds", action="store_true", help="also the sound files no timbre uses")
    ap.add_argument("--report", help="write the listing to FILE")
    a = ap.parse_args(argv)
    libs, cafs, missing = libraries(a.root, a.all_sounds)
    text = report(libs, cafs)
    if a.report:
        open(a.report, "w").write(text + "\n")
    else:
        print(text)
    for s, where in sorted(missing.items()):
        print("missing sound file %s (%s)" % (s, ", ".join(sorted(set(where)))))
    print("%d sub-catalogs, %d banks, %d sound files" % (
        len(libs), sum(len(x.listing) for x in libs), sum(len(x.sounds) for x in libs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
