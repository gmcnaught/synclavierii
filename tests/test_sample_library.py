#!/usr/bin/env python3
"""tools/sample_library.py: .caf -> NED sound file, banks packed by family,
and the W1: image tools/timbre_disk.py makes from them (synthetic data; the
NED libraries are not in the repository)."""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import sample_library as sl  # noqa: E402
from tools import timbre_disk  # noqa: E402
from tools.ned_disk import DiskWords, read_file, walk  # noqa: E402
from tools.stmb import MISC_TEMPLATE, MOR, NUM_PARAMS, TINFO_TEMPLATE, bank_bytes, name_words  # noqa: E402


def caf(samples, ch=1, little=True, valid=None, sectors=None, stereo=None):
    """A Synclavier3-style .caf: desc, SNCL (3 header sectors), data."""
    n = len(samples)
    hdr = [0] * 768
    hdr[0] = 4
    v = n if valid is None else valid
    hdr[2], hdr[3], hdr[4] = v >> 24, (v >> 8) & 0xFFFF, v & 0xFF
    hdr[7] = -(-n // 256) if sectors is None else sectors
    hdr[41] = (ch == 2) if stereo is None else stereo
    hdr[42] = 500

    def chunk(t, body):
        return t + struct.pack(">q", len(body)) + body
    desc = struct.pack(">d4sIIIII", 50000.0, b"lpcm", 2 if little else 0, 2 * ch, 1, ch, 16)
    pcm = struct.pack("%s%dh" % ("<" if little else ">", n), *samples)
    return (b"caff" + struct.pack(">HH", 1, 0) + chunk(b"desc", desc)
            + chunk(b"SNCL", struct.pack(">768H", *hdr)) + chunk(b"data", bytes(4) + pcm))


def timbre(name, sounds):
    """A one-partial timbre whose patch list names `sounds`."""
    frames = []
    for s in sounds:
        f = [MOR, 1, 48] + [ord((s + "\0" * 8)[i]) | ord((s + "\0" * 8)[i + 1]) << 8
                            for i in range(0, 8, 2)]
        frames.append(f + [0] * (48 - len(f)))
    tinfo = list(TINFO_TEMPLATE)
    tinfo[8:16] = name_words(name)
    return {"partials": [{"params": [0] * NUM_PARAMS, "frames": frames}, None, None, None],
            "tinfo": tinfo, "misc": MISC_TEMPLATE, "name": name}


def test_caf_sound():
    samples = [(k * 37) % 65536 - 32768 for k in range(300)]
    for little in (True, False):
        out = sl.caf_sound(caf(samples, little=little))
        w = struct.unpack(">%dH" % (len(out) // 2), out)
        assert len(out) == (3 + 2) * 512                     # 300 words: 2 data sectors
        assert w[0] == 4 and w[42] == 500                     # header verbatim
        assert [x - 65536 if x & 0x8000 else x for x in w[768:1068]] == samples
        assert not any(w[1068:])
    st = sl.caf_sound(caf(list(range(512)), ch=2))            # interleaved words kept
    assert struct.unpack(">512H", st[1536:2560]) == tuple(range(512))
    for bad in (caf([1, 2, 3], valid=4), caf([1, 2], ch=1, stereo=1), b"RIFF" + bytes(40),
                caf([0] * 10)[:-6]):
        try:
            sl.caf_sound(bad)
        except ValueError:
            continue
        raise AssertionError("accepted a bad file")


def _library(root):
    """Folders PNODTA40 (2 banks), HPCDTA40, SYNDTA40 and NED_TL23."""
    def stmb(folder, banks):
        os.makedirs(os.path.join(root, folder))
        open(os.path.join(root, folder, "*NEWDATA.stmb"), "wb").write(bank_bytes(banks, 192)[0])
    stmb("PNODTA40", [[timbre("PIANO A", ["PNOA", "PNOB"])], [timbre("PIANO B", ["PNOB"])]])
    stmb("HPCDTA40", [[timbre("HPC", ["HPC1"]), None, timbre("HPC 2", ["PNOA", "GONE"])]])
    stmb("SYNDTA40", [[timbre("SYN", ["SYN1"])]])
    os.makedirs(os.path.join(root, "NED_TL23"))
    for k, n in enumerate(["PNOA", "PNOB", "HPC1", "SYN1", "XTRA"]):
        open(os.path.join(root, "NED_TL23", n + ".caf"), "wb").write(caf([k] * (100 + k)))


def test_libraries_and_disk():
    with tempfile.TemporaryDirectory() as root:
        _library(root)
        libs, cafs, missing = sl.libraries(root)
        assert [x.name for x in libs] == ["PIANO", "SYNTH"]
        piano = libs[0]
        assert [(n, f, b) for n, f, b, _t in piano.listing] == [
            (1, "HPCDTA40", 1), (2, "PNODTA40", 1), (3, "PNODTA40", 2)]
        assert piano.sounds == ["HPC1", "PNOA", "PNOB"]
        assert missing == {"GONE": ["PIANO"]}
        libs_all = sl.libraries(root, all_sounds=True)[0]
        assert libs_all[-1].name == "SOUNDS1" and libs_all[-1].sounds == ["XTRA"]

        samples = [(x.name, x.newdata, [(s, sl.caf_sound(open(cafs[s], "rb").read()))
                                        for s in x.sounds]) for x in libs_all]
        disk = timbre_disk.make([], samples=samples)
        W = DiskWords(disk)
        ents = {p: t for p, t, _s, _l, _w in walk(W)}
        assert ents["/PIANO"] == 6 and ents["/PIANO/.NEWDATA"] == 3 and ents["/PIANO/PNOB"] == 5
        assert "/SOUNDS1/.NEWDATA" not in ents and ents["/SOUNDS1/XTRA"] == 5
        got = read_file(W, "/PIANO/HPC1")
        assert got[768:768 + 102] == [2] * 102 and len(got) == 4 * 256
        nd = read_file(W, "/PIANO/.NEWDATA")
        assert struct.pack(">%dH" % len(nd), *nd) == piano.newdata


def test_large_subcatalog():
    """More than 32 files: a type-7 (128-entry) sub-catalog."""
    sounds = [("S%d" % k, sl.caf_sound(caf([k] * 10))) for k in range(40)]
    disk = timbre_disk.make([], samples=[("BIG", None, sounds)])
    ents = {p: t for p, t, _s, _l, _w in walk(DiskWords(disk))}
    assert ents["/BIG"] == 7 and ents["/BIG/S39"] == 5
    try:
        timbre_disk.make([], samples=[("HUGE", None, sounds * 4)])
    except ValueError:
        pass
    else:
        raise AssertionError("160 files accepted in one sub-catalog")


def test_family_packing():
    src = [("PNODTA%02d" % k, 1, [None]) for k in range(6)] + [("PNODTA71", b, [None]) for b in range(1, 9)]
    src += [("HPCDTA40", 1, [None])]
    groups = sl.group_banks(src)
    assert [n for n, _b in groups] == ["PIANO1", "PIANO2", "PIANO3"]
    assert [f for f, _b, _t in groups[1][1]] == ["PNODTA71"] * 8      # an 8-bank file stays whole
    assert sl.family_of("AM-DATA") == "SYNTH" and sl.family_of("ZZZDTA01") == "OTHER"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
