#!/usr/bin/env python3
"""The repository holds no NED disk images, timbre/sound files or other
binaries that are not ours to redistribute (README "Licence and
provenance"). Checks the files git tracks.

Run:  python3 tests/test_repo_hygiene.py
"""
import os
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


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def test_no_forbidden_types():
    bad = [p for p in tracked() if p.lower().endswith(FORBIDDEN)]
    assert not bad, "files that must not be committed: %s" % bad


def test_no_large_files():
    big = []
    for p in tracked():
        full = os.path.join(ROOT, p)
        if os.path.isfile(full) and os.path.getsize(full) > MAX_BYTES:
            big.append(p)
    assert not big, "files over %d bytes (binaries?): %s" % (MAX_BYTES, big)


if __name__ == "__main__":
    if not os.path.isdir(os.path.join(ROOT, ".git")) and \
            not os.path.isfile(os.path.join(ROOT, ".git")):
        print("not a git checkout; skipped")
        sys.exit(0)
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
