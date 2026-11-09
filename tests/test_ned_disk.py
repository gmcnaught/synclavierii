#!/usr/bin/env python3
"""tools/ned_disk.py: adding a file to a hard-disk image's root catalog."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools.ned_disk import SECTOR_WORDS, add_root_file, load_bytes, read_file, walk  # noqa: E402


def _disk(sectors=64):
    d = bytearray(sectors * SECTOR_WORDS * 2)
    # root catalog (sectors 0-3): MONITOR at 4, 2 sectors, 300 words, exec
    d[0:16] = struct.pack(">8H", 0x4F4D, 0x494E, 0x4F54, 0x0052, 4, 2, 300, 1)
    return d


def test_add_root_file():
    d = _disk()
    data = struct.pack(">600H", *range(600))           # 3 sectors, last one partial
    assert add_root_file(d, ".NEWDATA", data) == 6     # after MONITOR (4 + 2)
    W = load_bytes(d)
    entries = {p: (typ, start, length, words) for p, typ, start, length, words in walk(W)}
    assert entries["/.NEWDATA"] == (3, 6, 3, 600)
    assert read_file(W, ".NEWDATA") == list(range(600))
    assert "/MONITOR" in entries


def test_add_root_file_errors():
    d = _disk(8)
    for args in ((".NEWDATA", bytes(3 * SECTOR_WORDS * 2)),    # 6 + 3 > 8 sectors
                 ("TOOLONGNAME", b"")):
        try:
            add_root_file(d, *args)
        except ValueError:
            pass
        else:
            raise AssertionError("no error for %s" % args[0])
    add_root_file(d, "A", bytes(2))
    try:
        add_root_file(d, "A", bytes(2))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate name accepted")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
