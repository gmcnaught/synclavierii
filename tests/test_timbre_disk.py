#!/usr/bin/env python3
"""tools/timbre_disk.py: a W1: image with one sub-catalog per timbre library."""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import timbre_disk  # noqa: E402
from tools.ned_disk import load, read_file, walk  # noqa: E402


def test_names():
    assert timbre_disk.short_name("x/System-Disk.stmb") == "SYSDISK"
    assert timbre_disk.short_name("Timbre-Disk-3.stmb") == "TIMBDSK3"
    assert timbre_disk.short_name("Resynth-Library-6.stmb") == "RESYNTH6"
    assert timbre_disk.short_name("Test-Timbres.stmb") == "TESTTIMB"
    assert timbre_disk.short_name("my lib (2).stmb") == "MYLIB2"


def test_disk():
    libs = [("LIBA", bytes((k * 3) & 0xFF for k in range(192 * 512))),
            ("LIBB", bytes((k * 5 + 1) & 0xFF for k in range(250 * 8 * 512)))]
    disk = timbre_disk.make(libs)
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "W1.IMG")
        open(img, "wb").write(disk)
        W = load(img)
    ents = {p: (t, s, ln) for p, t, s, ln, w in walk(W)}
    assert ents["/LIBA"][0] == 6 and ents["/LIBA/.NEWDATA"] == (3, ents["/LIBA"][1] + 1, 192)
    assert ents["/LIBB/.NEWDATA"][2] == 2000
    for name, data in libs:
        got = read_file(W, "/%s/.NEWDATA" % name)
        assert struct.pack(">%dH" % len(got), *got) == data
    for bad in ([("X", bytes(100 * 512))], [("A", bytes(192 * 512)), ("A", bytes(192 * 512))],
                [("TOOLONGNAME", bytes(192 * 512))]):
        try:
            timbre_disk.make(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
