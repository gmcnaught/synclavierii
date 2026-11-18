#!/usr/bin/env python3
"""tools/seq_record.py (note lists, Standard MIDI Files, sequence files) and
the DEMOS sub-catalog of tools/timbre_disk.py. Standard library only.

With SYNCLAVIER_W0 naming a SYN-5.3 W0 image that holds .NEWDATA (e.g.
W0-53.IMG from tools/w0_image.py), test_record_in_simulator records two
short parts in the simulator and checks the saved .SQ1DATA (about 90 s).
"""
import os
import struct
import sys
import tempfile
from fractions import Fraction

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from tools import seq_record as sr  # noqa: E402
from tools import timbre_disk  # noqa: E402
from tools.ned_disk import load, read_file, walk  # noqa: E402


def test_note_names():
    assert sr.note_number("C4") == 60 and sr.note_number("F#3") == 54
    assert sr.note_number("Bb2") == 46 and sr.note_number("61") == 61
    for k in range(21, 109):
        assert sr.note_number(sr.note_name(k)) == k
    assert sr.fold(30) == 42 and sr.fold(110) == 98 and sr.fold(60) == 60


TEXT = """title: Test
beat: 600
time: 3/4   # a comment
part: Upper | key=G | clef=G
0 1 D5
1 1/2 F#4 90
3/2 0.5 G4
part: Lower | key=G | clef=F
# whole line comment
0 3 G3
"""


def test_text_round_trip():
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "a.txt")
        open(a, "w").write(TEXT)
        p = sr.read_text(a)
        assert (p.title, p.beat_ms, p.time) == ("Test", 600, "3/4")
        assert [(x.name, x.key, x.clef, len(x.notes)) for x in p.parts] == \
            [("Upper", "G", "G", 3), ("Lower", "G", "F", 1)]
        n = p.parts[0].notes[1]
        assert (n.start, n.dur, n.key, n.vel) == (1, Fraction(1, 2), 66, 90)
        b = os.path.join(d, "b.txt")
        with open(b, "w") as f:
            sr.write_text(p, f)
        q = sr.read_text(b)
        assert [[(n.start, n.dur, n.key, n.vel) for n in x.notes] for x in q.parts] == \
            [[(n.start, n.dur, n.key, n.vel) for n in x.notes] for x in p.parts]


def _smf():
    """Format 1, 480 ticks/quarter: a conductor track (tempo 600 ms, 3/4, one
    sharp) and a track with two channels."""
    def vl(v):
        out = [v & 0x7F]
        v >>= 7
        while v:
            out.insert(0, 0x80 | v & 0x7F)
            v >>= 7
        return bytes(out)

    def track(events):
        body = b"".join(vl(dt) + ev for dt, ev in events) + b"\x00\xff\x2f\x00"
        return b"MTrk" + struct.pack(">I", len(body)) + body
    conductor = track([(0, b"\xff\x51\x03" + (600000).to_bytes(3, "big")),
                       (0, b"\xff\x58\x04\x03\x02\x18\x08"), (0, b"\xff\x59\x02\x01\x00")])
    notes = track([(0, b"\xff\x03\x04Duet"),
                   (0, b"\x90\x4a\x64"), (0, b"\x91\x37\x50"),
                   (480, b"\x80\x4a\x00"), (0, b"\x90\x48\x64"),     # D5 1 beat, C5 next
                   (240, b"\x48\x00"),                              # running status, vel 0 = off
                   (720, b"\x81\x37\x00")])                         # G3 3 beats
    return b"MThd" + struct.pack(">IHHH", 6, 1, 2, 480) + conductor + notes


def test_read_midi():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.mid")
        open(path, "wb").write(_smf())
        p = sr.read_midi(path)
    assert (p.beat_ms, p.time) == (600, "3/4")
    assert [(x.name, x.key, x.clef) for x in p.parts] == [("Duet", "G", "G"), ("Duet", "G", "F")]
    assert [(n.start, n.dur, n.key, n.vel) for n in p.parts[0].notes] == \
        [(0, 1, 74, 100), (1, Fraction(1, 2), 72, 100)]
    assert [(n.start, n.dur, n.key) for n in p.parts[1].notes] == [(0, 3, 55)]


def test_split_voices():
    part = sr.Part("SA")
    for s, d, k in ((0, 1, 67), (0, 1, 62), (1, 2, 67), (1, Fraction(1, 2), 64),
                    (Fraction(3, 2), Fraction(3, 2), 66), (3, 1, 67)):    # unison at 3
        part.notes.append(sr.Note(s, d, k))
    up, lo = sr.split_voices(part)
    assert [(n.start, n.key) for n in up.notes] == [(0, 67), (1, 67), (3, 67)]
    assert [(n.start, n.key) for n in lo.notes] == [(0, 62), (1, 64), (Fraction(3, 2), 66), (3, 67)]


def _sequence(notes, click=500):
    """Words of a minimal sequence file: base sector, note area header at
    sector 2, track header for track button 1 (absolute track 2) at 3 and one
    note list segment at 4 with 2-word records."""
    W = [0] * (5 * sr.SECTOR)
    W[sr.SEQ_CLICK], W[sr.SEQ_NAH] = click, 2
    W[2 * sr.SECTOR + sr.FIRST_TRACK] = 1               # track header: NAH + 1
    W[3 * sr.SECTOR] = 2                                # THD.FOR: first NLS at NAH + 2
    base, wrd, t = 4 * sr.SECTOR, 8, 0
    W[base + 3] = wrd
    for start, key, dur in notes:
        delta, t = start - t, start
        exp = 0
        while dur >= 4096:
            dur //= 4
            exp += 1
        W[base + wrd] = exp << 13 | (dur >> 10 & 3) << 11 | delta << 1
        W[base + wrd + 1] = (dur & 1023) << 6 | (key - sr.VPK_KEY_OFFSET)
        wrd += 2
    W[base + wrd] = 0xFFFF
    W[base + 4] = wrd
    return W


def test_seq_notes():
    W = _sequence([(50, 60, 470), (550, 62, 5000), (1050, 64, 235)])
    assert sr.seq_notes(W) == [(1, 50, 60, 470), (1, 550, 62, 1250 * 4), (1, 1050, 64, 235)]
    p = sr.Piece()
    part = sr.Part("x")
    part.notes = [sr.Note(0, 1, 60), sr.Note(1, 10, 62), sr.Note(2, Fraction(1, 2), 64), sr.Note(3, 1, 65)]
    p.parts = [part]
    assert sr.compare(p, W) == [(4, 1, 0, 0, 30)]       # F4 missing; 500-470 = 30 ms


def test_data_pieces():
    """The note lists in data/sequences parse, with sources and licences."""
    d = os.path.join(ROOT, "data", "sequences")
    want = {"bach-bwv269-chorale.txt": 4, "bach-bwv-anh114-minuet.txt": 2,
            "brahms-op51-2-iii-minuetto.txt": 4, "brahms-op51-2-iii-allegretto.txt": 4}
    for name, nparts in want.items():
        p = sr.read_text(os.path.join(d, name))
        info = dict(p.info)
        assert len(p.parts) == nparts and all(x.notes for x in p.parts), name
        assert info.get("source", "").startswith("https://") and info.get("licence"), name
        for x in p.parts:
            assert all(33 <= n.key <= 108 and n.dur > 0 for n in x.notes), (name, x.name)


def test_demos_subcatalog():
    seqs = {"DEMOS": {0: bytes(range(256)) * 48, 1: b"\x12\x34" * 300}}
    disk = timbre_disk.make([], sequences=seqs)
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "W1.IMG")
        open(img, "wb").write(disk)
        W = load(img)
    ents = {p: (t, ln) for p, t, s, ln, w in walk(W)}
    assert ents["/DEMOS"] == (6, 1 + 24 + 2)
    assert ents["/DEMOS/.SQ0DATA"] == (4, 24) and ents["/DEMOS/.SQ1DATA"] == (4, 2)
    got = read_file(W, "/DEMOS/.SQ1DATA")
    assert struct.pack(">%dH" % len(got), *got) == seqs["DEMOS"][1]
    for bad in ({"DEMOS": {8: b"\0\0"}}, {"TOOLONGNAME": {0: b"\0\0"}}):
        try:
            timbre_disk.make([], sequences=bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_record_in_simulator():
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        print("  skip test_record_in_simulator (SYNCLAVIER_W0 not set)")
        return
    if "/.NEWDATA" not in {p for p, *_ in walk(load(image))}:
        print("  skip test_record_in_simulator (%s has no .NEWDATA; use tools/w0_image.py)" % image)
        return
    p = sr.Piece()
    p.beat_ms = 400
    a, b = sr.Part("upper"), sr.Part("lower")
    a.notes = [sr.Note(i, 1, k) for i, k in enumerate((72, 74, 76, 77))] + [sr.Note(4, Fraction(1, 2), 79)]
    b.notes = [sr.Note(0, 2, 48), sr.Note(2, 2, 43), sr.Note(Fraction(9, 2), Fraction(1, 2), 48)]
    p.parts = [a, b]
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "t.sseq")
        W, s = sr.record(p, image, 1, out, log=lambda m: None)
        assert sr.words(open(out, "rb").read()) == W
    assert sr.seq_header(W)["click_ms"] == 400 and sr.seq_header(W)["magic"] == "0o123462"
    for n, missing, extra, dt, dd in sr.compare(p, W):
        assert missing == 0 and extra == 0 and dt <= 10 and dd <= 60, (n, missing, extra, dt, dd)


MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Two Staves</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>1</fifths></key>
        <time><beats>3</beats><beat-type>4</beat-type></time><staves>2</staves>
        <clef number="1"><sign>G</sign></clef><clef number="2"><sign>F</sign></clef></attributes>
      <direction><sound tempo="120"/></direction>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>2</duration><staff>1</staff></note>
      <note><chord/><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch><duration>2</duration><staff>1</staff></note>
      <note><rest/><duration>2</duration><staff>1</staff></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff>
        <tie type="start"/></note>
      <backup><duration>6</duration></backup>
      <note><pitch><step>G</step><octave>2</octave></pitch><duration>6</duration><staff>2</staff></note>
    </measure>
    <measure number="2">
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><staff>1</staff>
        <tie type="stop"/></note>
      <note><grace/><pitch><step>A</step><octave>4</octave></pitch><staff>1</staff></note>
      <note><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch><duration>1</duration><staff>1</staff></note>
    </measure>
  </part>
</score-partwise>
"""


def test_musicxml():
    import zipfile
    with tempfile.TemporaryDirectory() as d:
        xml = os.path.join(d, "t.musicxml")
        with open(xml, "w") as f:
            f.write(MUSICXML)
        mxl = os.path.join(d, "t.mxl")
        with zipfile.ZipFile(mxl, "w") as z:
            z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="score.xml"/>'
                       '</rootfiles></container>')
            z.writestr("score.xml", MUSICXML)
        for path in (xml, mxl):
            p = sr.read_piece(path)
            assert p.title == "Two Staves" and p.beat_ms == 500 and p.time == "3/4"
            rh, lh = p.parts
            assert (rh.key, rh.clef, lh.clef) == ("G", "G", "F")
            assert [(n.start, n.dur, n.key) for n in rh.notes] == [
                (0, 1, 66), (0, 1, 74), (2, Fraction(3, 2), 67), (Fraction(7, 2), Fraction(1, 2), 70)]
            assert [(n.start, n.dur, n.key) for n in lh.notes] == [(0, 3, 43)]


def test_install():
    from tools.ned_disk import add_file, blank_disk, load_bytes, walk
    with tempfile.TemporaryDirectory() as d:
        w0 = os.path.join(d, "w0.img")
        disk = blank_disk(2)
        add_file(disk, ".SQ5DATA", bytes(512 * 6), typ=4)          # an existing slot is replaced
        open(w0, "wb").write(disk)
        seq = os.path.join(d, "s.sseq")
        open(seq, "wb").write(struct.pack(">300H", *range(300)))
        out = os.path.join(d, "out.img")
        assert sr.main(["install", seq, "--w0", w0, "--slot", "5", "--out", out]) == 0
        W = load_bytes(open(out, "rb").read())
        files = [(p, t) for p, t, *_ in walk(W)]
        assert files.count(("/.SQ5DATA", 4)) == 1
        assert read_file(W, ".SQ5DATA")[:300] == list(range(300))


def test_musicxml_velocity():
    with tempfile.TemporaryDirectory() as d:
        xml = os.path.join(d, "t.musicxml")
        with open(xml, "w") as f:
            f.write(MUSICXML.replace("<staff>1</staff>", "<voice>2</voice><staff>1</staff>", 1))
        v = sr.parse_velocity("1/2=110, 2/1=85,1/1=55")
        assert v == {(1, 2): 110, (2, 1): 85, (1, 1): 55}
        rh, lh = sr.read_piece(xml, v).parts
        # the first D5 is voice 2 (melody); the rest of staff 1 voice 1; the bass staff 2 voice 1
        assert [(n.key, n.vel) for n in rh.notes] == [(66, 55), (74, 110), (67, 55), (70, 55)]
        assert [n.vel for n in lh.notes] == [85]
        assert [n.vel for n in sr.read_piece(xml).parts[0].notes] == [90] * 4


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
