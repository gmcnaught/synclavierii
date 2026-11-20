#!/usr/bin/env python3
"""The repository holds no NED disk images, timbre/sound files or other
binaries that are not ours to redistribute (README "Licence and
provenance"). Checks the files git tracks.

The one exception is the released cores, MiSTer-devel style:
releases/Synclavier_YYYYMMDD.rbf (committed by .github/workflows/release.yml).
releases/ holds only those and the MGLs, because Distribution_MiSTer copies
every other undated file in it to games/Synclavier/ on users' SD cards.

Run:  python3 tests/test_repo_hygiene.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# NED disk images, timbre banks, sound files, sound programs, sequences
# (generated ones too: tools/seq_record.py), MIDI/MusicXML downloads, images built
# from them, state images, ROM dumps, built cores, photos.
FORBIDDEN = (".simg", ".stmb", ".ssnd", ".sprg", ".sseq", ".img", ".sst", ".bin",
             ".rom", ".rbf", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
             ".pdf", ".docx", ".zip", ".mid", ".midi", ".mxl")
MAX_BYTES = 256 * 1024     # the largest tracked file is under 100 KB
RELEASE_RBF = re.compile(r"^releases/Synclavier_20\d{6}\.rbf$")


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def test_no_forbidden_types():
    bad = [p for p in tracked()
           if p.lower().endswith(FORBIDDEN) and not RELEASE_RBF.match(p)]
    assert not bad, "files that must not be committed: %s" % bad


def test_no_large_files():
    big = []
    for p in tracked():
        if RELEASE_RBF.match(p):
            continue
        full = os.path.join(ROOT, p)
        if os.path.isfile(full) and os.path.getsize(full) > MAX_BYTES:
            big.append(p)
    assert not big, "files over %d bytes (binaries?): %s" % (MAX_BYTES, big)


def test_releases_folder():
    bad = [p for p in tracked() if p.startswith("releases/")
           and not (RELEASE_RBF.match(p) or
                    re.match(r"^releases/[^/]+\.mgl$", p))]
    assert not bad, "releases/ holds only Synclavier_YYYYMMDD.rbf and " \
        "MGLs: %s" % bad


if __name__ == "__main__":
    if not os.path.isdir(os.path.join(ROOT, ".git")) and \
            not os.path.isfile(os.path.join(ROOT, ".git")):
        print("not a git checkout; skipped")
        sys.exit(0)
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
