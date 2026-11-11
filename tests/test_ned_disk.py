#!/usr/bin/env python3
"""tools/ned_disk.py: adding a file to a hard-disk image's root catalog."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools.ned_disk import (SECTOR_WORDS, DiskWords, add_file, add_root_file,  # noqa: E402
                            entry_fields, entry_words, load_bytes, read_file, walk)


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


def test_entry_high_bits():
    """Start bits 16-23 in type-word bits 8-15, length bits 16-19 in bits
    4-7 (XPL/CATCODE GET_FCB)."""
    e = entry_words([1, 2, 3, 4], 0x12_3456, 0x7_89AB, 0x1234, 5)
    assert e[4:] == [0x3456, 0x89AB, 0x1234, 0x12 << 8 | 0x7 << 4 | 5]
    assert entry_fields(e) == (0x12_3456, 0x7_89AB, 0x1234, 5)
    for bad in ((1 << 24, 1), (0, 1 << 20)):
        try:
            entry_words([0] * 4, *bad, 0, 3)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_files_above_32mb():
    """A sub-catalog placed beyond sector 65535 and its files read back."""
    d = bytearray(40 << 20)                            # 81920 sectors
    add_root_file(d, "PAD", bytes(70000 * 512))        # sectors 4..70003
    add_file(d, "SUB", bytes(10 * 512), typ=7)         # 4-sector catalog + 6
    add_file(d, "SUB/SND", struct.pack(">600H", *range(600)), typ=5)
    W = DiskWords(d)
    ents = {p: (typ, start, length, words) for p, typ, start, length, words in walk(W)}
    assert ents["/SUB"] == (7, 70004, 10, 2560)
    assert ents["/SUB/SND"] == (5, 70008, 3, 600)
    assert read_file(W, "SUB/SND") == list(range(600))
    raw = load_bytes(d)[8:16]                          # the SUB entry's words
    assert raw[4] == 70004 & 0xFFFF and raw[7] == 1 << 8 | 7


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
