#!/usr/bin/env python3
"""tools/music_printing.py (NED Music Printing on a W0 image) and the
PostScript side of tools/print_render.py.

With SYNCLAVIER_W0_RAW (Synclavier3's "W0 Disk Image.simg") the install is
checked on a real W0; with MUSIC_PRINTING_OUT (a `music_printing.py build`
OUTDIR) too, the installed files are the built ones."""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import music_printing, print_render  # noqa: E402
from tools.ned_disk import load, read_file, walk  # noqa: E402


def test_able_text():
    """CR-ended lines: line number, characters two to a word (first low),
    the odd last character or a 0 word to end the line."""
    data = music_printing.able_text(b"abc\rde\r\rf")
    assert struct.unpack(">%dH" % (len(data) // 2), data) == (
        1, ord("a") | ord("b") << 8, ord("c"), 2, ord("d") | ord("e") << 8, 0, 3, 0, 4, ord("f"))
    assert struct.unpack(">2H", music_printing.able_text(b"f")) == (1, ord("f"))


def test_postscript_cleanup():
    raw = b"\x14\x14%!PS-Adobe-2.0\r%%Title: x\rserverdict begin 0 exitserver\r/a 1 def\rshowpage\r\x04"
    ps = print_render.postscript(raw)
    assert ps == b"%!PS-Adobe-2.0\n%%Title: x\n\n/a 1 def\nshowpage\n"
    assert print_render.postscript(b"\r\n\x14plain text") is None


def test_install_on_w0():
    """Install leaves every other file's contents as they were (a large,
    type-7 .SYSTEM catalog: 128 entries), and puts the given data in."""
    raw = os.environ.get("SYNCLAVIER_W0_RAW")
    if not raw:
        print("  skip test_install_on_w0 (SYNCLAVIER_W0_RAW not set)")
        return
    out = os.environ.get("MUSIC_PRINTING_OUT")
    if out:
        files = music_printing.mplt_files(out)
    else:                                       # stand-ins: some fit their slots, .SCWT-7 does not
        files = [(n, bytes((i * 7 + k) & 0xFF for k in range(2 * (600 + 97 * i))), t)
                 for i, (n, _f, t) in enumerate(music_printing.FILES)]
    from tools.w0_image import prepared_disk
    disk = bytearray(prepared_disk(raw, 30, None))
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "W0.IMG")
        open(img, "wb").write(disk)
        W0 = load(img)
        before = {p: list(read_file(W0, p)) for p, t, s, ln, w in walk(W0) if t not in (6, 7)}
        assert "/.SYSTEM/.HELP" in before and "/.SYSTEM/.SPLT-7" in before
        done = music_printing.install(disk, files)
        open(img, "wb").write(disk)
        W = load(img)
        names = {"/.SYSTEM/" + n for n, _d, _t in files}
        for p, words in before.items():
            if p not in names:
                assert list(read_file(W, p)) == words, p
        for name, data, typ in files:
            got = read_file(W, "/.SYSTEM/" + name)
            assert struct.pack(">%dH" % len(got), *got)[:len(data)] == data, name
    if out:                                     # Synclavier3's W0 has the data files
        assert dict(done)[".SPLT-7"] == "replaced", done
        assert all(a == "unchanged" for n, a in done if n in (".SAUX-7", ".SCWT-7", ".SFRM-7", ".SLIB-7")), done


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
