#!/usr/bin/env python3
"""Record a multi-part piece into SYN-5.3's memory recorder in the simulator
and save it as a sequence file (.SQnDATA), as a player would on the panel.

    seq_record.py record PIECE --w0 W0.IMG --slot N --sseq OUT.sseq [options]
    seq_record.py view --w0 W0.IMG [--w1 W1.IMG --catalog W1:DEMOS] --slot N
                       --piece PIECE.txt --png PREFIX [--pages K] [--play S] [--print F]
    seq_record.py show FILE.sseq            # header and notes of a sequence
    seq_record.py convert IN.mid OUT.txt [--split 1,2] [--shift B] [--beat-ms MS]

PIECE is a Standard MIDI File (.mid; one part per track and channel) or a
note list (.txt, format below). The simulator boots SYN-5.3 from the W0
image (with the VPK panel), recalls a timbre (BANK/ENTRY), sets the click
rate with the CLICK button and the knob, then for part i (track button i):
presses the track button (solo + arm), RECORD, plays the part's keys at
their times, STOP, and the track button again (unsolo). Finally ENTRY
WRITE + SEQUENCE + button N writes .SQnDATA through SYN-5.3's own save
path (SYNRSOU/05-BUTT/175-PRF5 SEQUENCER.RECALL.BUTTON, WRITE.SEQUENCE),
so the file is valid by construction. The file is copied out of the
simulator's in-memory W0 to OUT.sseq (big-endian words, as NED's .sseq)
and checked against the piece. `view` recalls a sequence, plays it
(counting FM register writes), sets up Music Notation (K) and saves its
screens as PNG (and, with --print, the H hardcopy's printer bytes).

Timing [OBS, simulator]: the recorder starts about 60 ms after the RECORD
press; sequence time 50 ms (ZERO.TIME, SYNLITS/GLOBLITS) is beat 1, so
beat b is played at RECORD + OFFSET_MS + b * click. Keys are scanned every
5 ms, so note starts land within 5 ms of the grid (`show` lists them).
Music Notation (Main Menu K) places notes on a grid of the sequence's click
rate (SAMP.CLICK.RATE, saved as word 13 of the file); the time signature,
key and clef are Music Notation screen settings, not part of the file.

Note list format (one item per line; '#' after a space or at the start
of a line begins a comment):

    title: Minuet in G
    beat: 500              # ms per beat (the click rate); default 500
    time: 3/4              # Music Notation TimeSig (a display hint)
    measures: 4            # measures per Music Notation screen (a hint)
    part: Right hand | key=G | clef=G
    0 1 D5                 # start and length in beats, note [velocity]
    1 1/2 G4 90            # beats may be fractions or decimals
    part: Left hand | key=G | clef=F
    0 3 G3

Notes are names (C4 = MIDI 60, sharps '#', flats 'b') or MIDI numbers. The
VPK has 76 keys (MIDI 33-108); notes outside are moved by octaves. A
part's key and clef are Music Notation's names: keys C G D A E B F# C# F
Bf Ef Af Df Gf Cf (the major key of the signature), clefs G A (alto) T F.
"""
import argparse
import os
import re
import struct
import sys
import tempfile
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --------------------------------------------------------------------------
# Pieces

NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
KEY_BY_SHARPS = {0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#",
                 -1: "F", -2: "Bf", -3: "Ef", -4: "Af", -5: "Df", -6: "Gf", -7: "Cf"}


class Note:
    __slots__ = ("start", "dur", "key", "vel")

    def __init__(self, start, dur, key, vel=100):
        self.start, self.dur, self.key, self.vel = Fraction(start), Fraction(dur), int(key), int(vel)

    def __repr__(self):
        return "Note(%s, %s, %d, %d)" % (self.start, self.dur, self.key, self.vel)


class Part:
    def __init__(self, name="", key="C", clef="G"):
        self.name, self.key, self.clef, self.notes = name, key, clef, []


class Piece:
    def __init__(self):
        self.title = ""
        self.beat_ms = 500
        self.time = "4/4"
        self.measures = None
        self.parts = []
        self.info = []          # other "name: value" header lines, kept on write


def note_number(s):
    """'C4' -> 60, 'F#3' -> 54, 'Bb2' -> 46, '61' -> 61."""
    s = s.strip()
    if s.lstrip("-").isdigit():
        return int(s)
    if not s or s[0].upper() not in NOTE_NAMES:
        raise ValueError("bad note %r" % s)
    n, i = NOTE_NAMES[s[0].upper()], 1
    while i < len(s) and s[i] in "#b":
        n += 1 if s[i] == "#" else -1
        i += 1
    return n + 12 * (int(s[i:]) + 1)


def note_name(k):
    return ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B")[k % 12] + str(k // 12 - 1)


def read_text(path):
    p = Piece()
    part = None
    for ln, line in enumerate(open(path, encoding="utf-8"), 1):
        line = re.sub(r"(^|\s)#(\s.*)?$", "", line.rstrip("\n")).strip()   # '#' + space: comment
        if not line:
            continue
        head, sep, val = line.partition(":")
        if sep and not head.strip()[:1].isdigit():
            head, val = head.strip().lower(), val.strip()
            if head == "part":
                fields = [f.strip() for f in val.split("|")]
                part = Part(fields[0])
                for f in fields[1:]:
                    k, _s, v = f.partition("=")
                    setattr(part, k.strip(), v.strip())
                p.parts.append(part)
            elif head == "title":
                p.title = val
            elif head == "beat":
                p.beat_ms = int(val.split()[0])
            elif head == "time":
                p.time = val.split()[0]
            elif head == "measures":
                p.measures = int(val.split()[0])
            else:
                p.info.append((head, val))
            continue
        f = line.split()
        if part is None or len(f) not in (3, 4):
            raise ValueError("%s:%d: expected 'start length note [velocity]' after a part:" % (path, ln))
        part.notes.append(Note(Fraction(f[0]), Fraction(f[1]), note_number(f[2]),
                               int(f[3]) if len(f) > 3 else 100))
    return p


def write_text(p, f):
    if p.title:
        f.write("title: %s\n" % p.title)
    for k, v in p.info:
        f.write("%s: %s\n" % (k, v))
    f.write("beat: %d\ntime: %s\n" % (p.beat_ms, p.time))
    if p.measures:
        f.write("measures: %d\n" % p.measures)
    for part in p.parts:
        f.write("\npart: %s | key=%s | clef=%s\n" % (part.name or "Part", part.key, part.clef))
        for n in sorted(part.notes, key=lambda n: (n.start, n.key)):
            f.write("%s %s %s%s\n" % (n.start, n.dur, note_name(n.key),
                                      "" if n.vel == 100 else " %d" % n.vel))


def _varlen(d, i):
    v = 0
    while True:
        b = d[i]
        i += 1
        v = v << 7 | b & 0x7F
        if not b & 0x80:
            return v, i


def read_midi(path):
    """A Standard MIDI File (format 0 or 1, ticks per quarter) as a Piece:
    one part per (track, channel) with notes, in file order; beat = quarter
    note, beat_ms from the first Set Tempo (default 500), time and key from
    the first Time/Key Signature."""
    d = open(path, "rb").read()
    if d[:4] != b"MThd":
        raise ValueError("%s: not a Standard MIDI File" % path)
    hlen, fmt, ntrk, div = struct.unpack(">IHHH", d[4:14])
    if div & 0x8000:
        raise ValueError("SMPTE time division is not supported")
    p = Piece()
    tempo = sig = key = None
    i = 8 + hlen
    order = []
    parts = {}
    for t in range(ntrk):
        if d[i:i + 4] != b"MTrk":
            raise ValueError("%s: bad track %d" % (path, t))
        (tlen,) = struct.unpack(">I", d[i + 4:i + 8])
        j, end, tick, status, name = i + 8, i + 8 + tlen, 0, 0, ""
        held = {}
        while j < end:
            delta, j = _varlen(d, j)
            tick += delta
            if d[j] & 0x80:
                status = d[j]
                j += 1
            if status == 0xFF:
                mtype = d[j]
                ln, j = _varlen(d, j + 1)
                data = d[j:j + ln]
                j += ln
                if mtype == 0x51 and tempo is None:
                    tempo = int.from_bytes(data, "big")
                elif mtype == 0x58 and sig is None:
                    sig = "%d/%d" % (data[0], 1 << data[1])
                elif mtype == 0x59 and key is None:
                    key = KEY_BY_SHARPS.get(struct.unpack("b", data[:1])[0], "C")
                elif mtype == 0x03 and not name:
                    name = data.decode("latin-1").strip()
                elif mtype == 0x2F:
                    break
                continue
            if status in (0xF0, 0xF7):
                ln, j = _varlen(d, j)
                j += ln
                continue
            kind, ch = status & 0xF0, status & 0x0F
            n = 1 if kind in (0xC0, 0xD0) else 2
            a, b = d[j], d[j + 1] if n == 2 else 0
            j += n
            if kind == 0x90 and b:
                held.setdefault((ch, a), []).append((tick, b))
            elif kind in (0x80, 0x90):
                if held.get((ch, a)):
                    on, vel = held[(ch, a)].pop(0)
                    if (t, ch) not in parts:
                        parts[(t, ch)] = Part(name or "Track %d" % (t + 1))
                        order.append((t, ch))
                    parts[(t, ch)].notes.append(Note(Fraction(on, div), Fraction(tick - on, div), a, vel))
        i = end
    p.beat_ms = round(tempo / 1000) if tempo else 500
    p.time = sig or "4/4"
    p.parts = [parts[k] for k in order]
    for part in p.parts:
        part.key = key or "C"
        part.notes.sort(key=lambda n: (n.start, n.key))
        part.clef = "F" if sum(n.key for n in part.notes) / len(part.notes) < 60 else "G"
    p.title = os.path.splitext(os.path.basename(path))[0]
    return p


def read_piece(path):
    return read_midi(path) if path.lower().endswith((".mid", ".midi")) else read_text(path)


def split_voices(part, names=("upper", "lower")):
    """Split a two-voice part (e.g. soprano and alto on one MIDI track) into
    two parts: notes in start order; a note goes to the voice that is free
    at its start, the higher of two notes starting together to the upper
    voice, and when both voices are free and one note starts alone, to the
    voice whose last note was nearer in pitch. A single note where both
    voices end together is a unison (MIDI files hold one note for both
    voices): it goes to both. [CHOICE: a chorale heuristic; a voice that
    really rests there gets the note too.]"""
    voices = [Part("%s %s" % (part.name, n), part.key, part.clef) for n in names]
    end = [Fraction(-1), Fraction(-1)]
    last = [None, None]
    groups = {}
    for n in part.notes:
        groups.setdefault(n.start, []).append(n)
    for t in sorted(groups):
        g = sorted(groups[t], key=lambda n: -n.key)
        free = [v for v in (0, 1) if end[v] <= t]
        if len(g) >= 2 and len(free) == 2:
            pairs = [(0, g[0]), (1, g[-1])] + [(0, n) for n in g[1:-1]]
        elif len(g) == 1 and end[0] == end[1] == t:
            pairs = [(0, g[0]), (1, Note(g[0].start, g[0].dur, g[0].key, g[0].vel))]
        else:
            pairs = []
            for n in g:
                cand = [v for v in (0, 1) if end[v] <= t] or [min((0, 1), key=lambda v: end[v])]
                if len(cand) == 2:
                    v = min(cand, key=lambda v: abs(n.key - last[v]) if last[v] is not None else v)
                else:
                    v = cand[0]
                pairs.append((v, n))
                end[v] = t + n.dur
                last[v] = n.key
        for v, n in pairs:
            voices[v].notes.append(n)
            end[v] = max(end[v], t + n.dur)
            last[v] = n.key
    return voices


def shift(piece, beats):
    """Move every note `beats` later (e.g. put an upbeat at the end of an
    empty first bar, so Music Notation's barlines fall right)."""
    for part in piece.parts:
        for n in part.notes:
            n.start += beats


# --------------------------------------------------------------------------
# Sequence files (.SQnDATA): SYNLITS/THDLITS, SYNCLITS

SECTOR = 256
SEQ_SPEED, SEQ_CLICK, SEQ_CRM, SEQ_BPM, MAGIC, SEQ_NUMSEC, SEQ_NAH = 12, 13, 14, 19, 32, 63, 68
ZERO_TIME = 50                    # ms: sequence time of beat 1 (GLOBLITS)
FIRST_TRACK = 2                   # track button 1 = absolute track 2 (0, 1: keyboard)
VPK_KEY_OFFSET = 36               # stored key # = MIDI note - 36 (key # 24 = middle C)


def words(data):
    return list(struct.unpack(">%dH" % (len(data) // 2), bytes(data[:len(data) // 2 * 2])))


def seq_header(W):
    return {"speed": W[SEQ_SPEED], "click_ms": W[SEQ_CLICK], "crm": W[SEQ_CRM],
            "bpm": W[SEQ_BPM], "magic": oct(W[MAGIC]), "sectors": W[SEQ_NUMSEC]}


def seq_notes(W):
    """Notes of a sequence file's words: [(track button, start ms, MIDI note,
    duration ms)] in track order. Note records: word 1 bit 0 = 4-word record,
    bits 1-10 time delta (ms), 11-12 duration bits 10-11, 13-14 power-of-4
    exponent, bit 15 + type bits = long rest (32-bit delta follows); word 2
    bits 6-15 duration bits 0-9, bits 0-5 key # (63 = rest)
    (SYNLITS/SYNCLITS; SYNRSOU/04-SEQ/160SEQ0A ADVANCE.TO.NEXT.NOTE)."""
    nah = W[SEQ_NAH]
    out = []
    for trk in range(256):
        p = W[nah * SECTOR + trk]
        if not p:
            continue
        sec, t, guard = W[(nah + p) * SECTOR], 0, 0
        while sec and guard < 10000:
            guard += 1
            base = (nah + sec) * SECTOR
            wrd = W[base + 3]
            while 0 < wrd < SECTOR and W[base + wrd] != 0xFFFF:
                w1, w2 = W[base + wrd], W[base + wrd + 1]
                if w1 & 0o174001 == 0o100001:           # long rest: 32-bit delta
                    t += W[base + wrd + 1] << 16 | W[base + wrd + 2]
                    wrd += 4
                    continue
                t += w1 >> 1 & 1023
                four = w1 & 1
                if (w2 & 63) != 63 and not (four and W[base + wrd + 2] & 0x8000):
                    dur = ((w1 >> 1) & 0o6000 | w2 >> 6) * 4 ** (w1 >> 13 & 3)
                    out.append((trk - FIRST_TRACK + 1, t, (w2 & 63) + VPK_KEY_OFFSET, dur))
                wrd += 4 if four else 2
            sec = W[base]
    return out


def compare(piece, W, parts=None):
    """Recorded notes against the piece: (missing, extra, worst start error
    ms, worst length error ms) per part, matching by key and nearest start."""
    click = W[SEQ_CLICK]
    rec = seq_notes(W)
    res = []
    for i, part in enumerate(piece.parts if parts is None else parts):
        got = [(t, k, d) for trk, t, k, d in rec if trk == i + 1]
        want = [(ZERO_TIME + float(n.start) * click, fold(n.key), float(n.dur) * click) for n in part.notes]
        pool = sorted(got)
        worst_t = worst_d = 0
        missing = 0
        for t, k, d in want:
            best = min((g for g in pool if g[1] == k), key=lambda g: abs(g[0] - t), default=None)
            if best is None or abs(best[0] - t) > click / 4:
                missing += 1
                continue
            pool.remove(best)
            worst_t = max(worst_t, abs(best[0] - t))
            worst_d = max(worst_d, abs(best[2] - d))
        res.append((len(want), missing, len(pool), worst_t, worst_d))
    return res


# --------------------------------------------------------------------------
# The simulator

OFFSET_MS = 110        # RECORD press -> beat 1 (sequence time ZERO.TIME)
RELEASE_MS = 25        # keys go up this long before the note's end
STEP = 1000            # instructions per run() slice near an event (~1 ms)
REDRAW_QUIET = 6       # s without terminal output that ends a Music Notation redraw


def fold(key):
    while key < 33:
        key += 12
    while key > 108:
        key -= 12
    return key


class Synclavier:
    """SYN-5.3 in the simulator, driven through the VPK panel and the VT640."""

    def __init__(self, w0, w1=None, fm_voices=32, boot_s=12.0, log=print, printer=None):
        from sim.boot import boot_from_w0
        from sim.devices.poly import PolySynth
        self.log = log
        self.cpu, _ = boot_from_w0(w0, w1=w1, poly=PolySynth(), keyboard="vpk",
                                   fm_voices=fm_voices, terminal="vt640", mouse=True,
                                   printer=printer)
        self.kb = self.cpu.keyboard
        self.run(boot_s)
        self.log("booted: %s | %s" % self.display())

    # -- time --------------------------------------------------------------
    def run(self, sec):
        self.until(self.cpu.time_ns + int(sec * 1e9))

    def until(self, t_ns):
        cpu = self.cpu
        while cpu.time_ns < t_ns and not cpu.halted:
            left = (t_ns - cpu.time_ns) // 1000          # ~1 instruction per us
            cpu.run(max(STEP, min(20_000, left)) if left > 2 * STEP else STEP)
        if cpu.halted:
            raise RuntimeError("simulator halted: %s" % (cpu.halted,))

    # -- panel -------------------------------------------------------------
    def button(self, name, hold=0.1, gap=0.3):
        from sim.devices.synth import vpk_button_number
        b = vpk_button_number(name)
        self.kb.press_button(b)
        self.run(hold)
        self.kb.press_button(b, False)
        self.run(gap)

    def hold(self, name, down=True):
        from sim.devices.synth import vpk_button_number
        self.kb.press_button(vpk_button_number(name), down)

    def light(self, name):
        from sim.devices.synth import vpk_button_number
        return self.kb.light(vpk_button_number(name))

    def display(self):
        return self.kb.display_text()

    def timbre(self, bank=1, entry=2):
        """BANK n, ENTRY m (W0:.NEWDATA bank 1 entry 2: SIMPLE FM SINE)."""
        self.button("bankb")
        self.button("timb.%d" % (bank - 1))
        self.button("entryb")
        self.button("timb.%d" % (entry - 1))
        self.run(2)
        self.log("timbre: %s | %s" % self.display())

    def click_ms(self):
        """The click rate in ms, from the CLICK display ('12000 BEATS/MIN' =
        120.00 BPM; 99.67 BPM shows as '9967': two decimals below 184 BPM)."""
        top = self.display()[0]
        if "BEATS/MIN" not in top:
            return None
        bpm100 = int(top.split()[0])
        return round(6000000 / bpm100)

    def set_click(self, ms, tries=300):
        """CLICK, then the knob until the click rate is `ms` (SYNRSOU 06-MAIN
        395-UPDT: off centre by d (raw/3 >= 12) the value moves by an amount
        that grows with d, about every 10 ms; back near centre the
        accumulator resets, so a short push moves it one step). Below
        centre the period grows."""
        self.button("click")             # shows the rate; toggles the click on
        if self.light("click"):
            self.button("click")         # click (metronome) off, rate still shown
        for _ in range(tries):
            now = self.click_ms()
            if now is None:
                self.button("click")
                continue
            diff = ms - now
            if diff == 0:
                break
            if abs(diff) > 30:           # ~35 per second
                mag, sec = 60, min(2.0, 0.6 * abs(diff) / 35)
            else:                        # one step per push
                mag, sec = 48, 0.012
            self.kb.set_analog("knob", 128 - mag if diff > 0 else 128 + mag)
            self.run(sec)
            self.kb.set_analog("knob", 128)
            self.run(0.15)
        self.kb.set_analog("knob", 128)
        self.run(0.3)
        got = self.click_ms()
        self.log("click: %s ms (wanted %d) | %s" % (got, ms, self.display()[0]))
        if got != ms:
            raise RuntimeError("click rate %s, wanted %d" % (got, ms))

    # -- recording ---------------------------------------------------------
    def record_part(self, track, part, beat_ms, offset_ms=OFFSET_MS):
        """Record `part` on track button `track` (1..): solo/arm, RECORD,
        the keys at their beats, STOP, unsolo."""
        name = "trak.%d" % (track - 1)
        if not self.light(name):
            self.button(name)
        events = []
        for n in part.notes:
            k = fold(n.key) - 60 + 36            # NED key number (middle C = 36)
            on = float(n.start) * beat_ms
            off = max(on + 10, (float(n.start + n.dur)) * beat_ms - RELEASE_MS)
            events.append((on, 1, k, n.vel))
            events.append((off, 0, k, 0))
        events.sort(key=lambda e: (e[0], e[1]))   # releases first at equal times
        self.hold("record")
        t0 = self.cpu.time_ns
        self.run(0.05)
        self.hold("record", False)
        down = {}
        for at, on, k, vel in events:
            self.until(t0 + int((offset_ms + at) * 1e6))
            if on:
                if down.get(k):                   # same key again: lift it first
                    self.kb.press_key(k, False)
                    self.run(0.005)
                self.kb.press_key(k, True, vel)
                down[k] = down.get(k, 0) + 1
            elif down.get(k):
                down[k] -= 1
                if not down[k]:
                    self.kb.press_key(k, False)
        self.run(0.5)
        self.button("stop")
        self.run(0.5)
        if self.light(name):
            self.button(name)                     # unsolo: the next track records alone
        self.log("track %d (%s): %d notes | %s | %s" % ((track, part.name, len(part.notes)) + self.display()))

    def save(self, slot):
        """ENTRY WRITE held, SEQUENCE, button `slot`: writes .SQ<slot>DATA."""
        self.hold("entrywrt")
        self.run(0.3)
        self.button("seqb")
        self.button("timb.%d" % slot)
        self.run(3)
        msg = self.display()
        self.hold("entrywrt", False)
        self.run(0.5)
        self.log("save .SQ%dDATA: %s | %s" % ((slot,) + msg))
        if "WRITTEN" not in "".join(msg):
            raise RuntimeError("save failed: %s" % (msg,))

    def recall(self, slot):
        self.button("seqb")
        self.button("timb.%d" % slot)
        self.run(4)
        self.log("recall .SQ%dDATA: %s | %s" % ((slot,) + self.display()))

    def read_file(self, path, disk=None):
        """Words of file `path` ('.SQ1DATA', 'DEMOS/.SQ1DATA') on the
        in-memory W0 (or `disk`, e.g. self.cpu.w1)."""
        from tools.ned_disk import file_words, load_bytes, walk
        W = load_bytes((disk or self.cpu.w0).data)
        want = "/" + path.strip("/")
        for p, typ, start, length, nwords in walk(W):
            if p == want and typ not in (6, 7):
                return file_words(W, start, length, nwords)
        raise KeyError(path)

    # -- terminal / Music Notation -------------------------------------------
    def idle(self, quiet=1.5, cap=90):
        """Run until the terminal has sent nothing for `quiet` s (a screen
        redraw at 9600 baud takes several seconds)."""
        out = self.cpu.terminal.out
        n, last = len(out), self.cpu.time_ns
        end = self.cpu.time_ns + int(cap * 1e9)
        while self.cpu.time_ns < end:
            self.run(0.25)
            if len(out) != n:
                n, last = len(out), self.cpu.time_ns
            elif self.cpu.time_ns - last > quiet * 1e9:
                return True
        return False

    def type(self, text, quiet=1.5):
        """Type `text`; arrow keys (control characters) one at a time, each
        after the screen has settled (typed ahead, SYN-5.3 drops some)."""
        for c in text:
            self.cpu.terminal.feed(c.encode("latin-1"))
            if c == "\r":                      # a value: may redraw everything,
                self.idle(REDRAW_QUIET, cap=180)  # after a silent note-map pass
            else:
                self.idle(0.6 if c < " " else 0.05, cap=30)
        self.idle(quiet)

    def png(self, path):
        write_png(path, self.cpu.screen.g)

    UP, DOWN, RIGHT, LEFT = "\x0b", "\x0a", "\x0c", "\x08"   # SYNLITS/ASCIILIT u.arr ...

    def notation(self, staves, measures, time, keys=(), clefs=(), res=None):
        """Main Menu K (Music Notation), then its menu (SYNSOU/MNOTMOD
        MENUFNCS SEQED_MENU; arrows are ctrl-K/J/L/H, a value ends with
        RETURN): Staves, Measures, TimeSig; per staff Key, Clf and Res
        (keys: 'G', 'Bf', ...; clefs: G, A (alto), T, F). Staff i shows
        track i (the default). Ends with the cursor on Staves."""
        U, D, R = self.UP, self.DOWN, self.RIGHT
        self.type("K", REDRAW_QUIET)
        self.type("%d\r" % staves)                   # row 0 col 0: Staves
        self.type(D + "%d\r" % measures)             # row 1 col 0: Measures
        self.type(U + R + R + "%s\r" % time)         # row 0 col 2: TimeSig
        self.type(D + D + D)                          # staff 0, Key
        for st in range(staves):
            if st:
                self.type("=" + U + U)                # next staff (+4 rows), Key
            if st < len(keys) and keys[st] not in ("", "C"):
                self.type("%s\r" % keys[st])
            self.type(D)                              # Clf
            if st < len(clefs) and clefs[st] not in ("", "G"):
                self.type("%s\r" % clefs[st])
            self.type(D)                              # Res
            if res:
                self.type("%d\r" % res)
        self.type(U * (4 * staves + 4))               # back to the overall menu
        self._col = 0

    def notation_measure(self, m):
        """Show from measure m (0 = the first): Measure# (row 0, col 1);
        call after notation()."""
        if getattr(self, "_col", 0) != 1:
            self.type(self.RIGHT)
            self._col = 1
        self.type("%d\r" % m)

    def enter_catalog(self, name):
        """Subcatalog Directory (Main Menu D): `name` (e.g. W1:DEMOS), RETURN;
        SYN-5.3 returns to the Main Menu ("Current Catalog: W1:DEMOS"). No
        ESC there: SYN-5.3 would take it and the next key as an escape
        sequence (seen: ESC then K does not open Music Notation)."""
        self.type("D", 3)
        self.type(name + "\r", 3)
        rows = ["".join(chr(c) for c, _ in r) for r in self.cpu.screen.cells]
        line = next((r for r in rows if "Current Catalog:" in r), "")
        self.log(line.strip())
        if name.upper() not in line.upper():
            raise RuntimeError("catalog %s not entered: %r" % (name, line.strip()))

    def play(self, sec):
        """START, `sec` seconds, STOP; returns the FM register writes made
        while playing and in as long idle before it."""
        w = self.cpu.fm.writes
        self.run(sec)
        idle = self.cpu.fm.writes - w
        w = self.cpu.fm.writes
        self.button("start", gap=0)
        self.run(sec)
        self.button("stop")
        return self.cpu.fm.writes - w, idle

    def hardcopy(self, quiet=5, cap=600):
        """H on the Music Notation screen (needs printer=...): the bytes the
        printer port received (tools/print_render.py --raw renders them)."""
        pr = self.cpu.printer
        start = len(pr.out)
        self.cpu.terminal.feed(b"H")
        n, last = len(pr.out), self.cpu.time_ns
        end = self.cpu.time_ns + int(cap * 1e9)
        while self.cpu.time_ns < end:
            self.run(0.5)
            if len(pr.out) != n:
                n, last = len(pr.out), self.cpu.time_ns
            elif n > start and self.cpu.time_ns - last > quiet * 1e9:
                break
        return bytes(pr.out[start:])


def write_png(path, g, width=640):
    import zlib
    h = len(g) // width
    raw = b"".join(b"\0" + bytes(255 * (p & 1) for p in g[y * width:(y + 1) * width]) for y in range(h))

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, h, 8, 0, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def with_slots(w0, slots, sectors=512):
    """A temporary copy of W0 with empty .SQnDATA files for `slots` that it
    lacks (SYN-5.3 writes a sequence only over an existing file of enough
    sectors, 175-PRF5). Returns the copy's path."""
    from tools.ned_disk import add_file, load_bytes, walk
    disk = bytearray(open(w0, "rb").read())
    have = {p for p, *_ in walk(load_bytes(disk))}
    for n in slots:
        if "/.SQ%dDATA" % n not in have:
            add_file(disk, ".SQ%dDATA" % n, bytes(sectors * 2 * SECTOR), typ=4)
    fd, path = tempfile.mkstemp(suffix=".IMG")
    with os.fdopen(fd, "wb") as f:
        f.write(disk)
    return path


def record(piece, w0, slot, sseq, parts=None, bank=1, entry=2, log=print, offset_ms=OFFSET_MS):
    """Record `piece` (parts: 0-based indices, default all) into .SQ<slot>DATA
    and write it to `sseq`. Returns (words, Synclavier)."""
    chosen = [piece.parts[i] for i in parts] if parts else piece.parts
    if len(chosen) > 32:
        raise ValueError("at most 32 tracks")
    img = with_slots(w0, [slot])
    try:
        s = Synclavier(img, log=log)
    finally:
        os.unlink(img)
    s.timbre(bank, entry)
    s.set_click(piece.beat_ms)
    for i, part in enumerate(chosen):
        s.record_part(i + 1, part, piece.beat_ms, offset_ms)
    s.save(slot)
    W = s.read_file(".SQ%dDATA" % slot)
    if 0 < W[SEQ_NUMSEC] * SECTOR <= len(W):
        W = W[:W[SEQ_NUMSEC] * SECTOR]            # the sequence, not the whole slot
    with open(sseq, "wb") as f:
        f.write(struct.pack(">%dH" % len(W), *W))
    for i, (n, miss, extra, dt, dd) in enumerate(compare(piece, W, chosen)):
        log("check track %d: %d notes, %d missing, %d extra, start error <= %d ms, "
            "length error <= %d ms" % (i + 1, n, miss, extra, dt, dd))
    return W, s


def view(a):
    p = read_piece(a.piece) if a.piece else Piece()
    staves = a.staves or len(p.parts) or 1
    keys = a.keys.split(",") if a.keys else [x.key for x in p.parts]
    clefs = a.clefs.split(",") if a.clefs else [x.clef for x in p.parts]
    measures = a.measures or p.measures or 2
    s = Synclavier(a.w0, w1=a.w1, printer="prism" if a.prn else None)
    if a.catalog:
        s.enter_catalog(a.catalog)
    s.recall(a.slot)
    if a.play:
        playing, idle = s.play(a.play)
        print("playback: %d FM register writes in %g s (idle: %d)" % (playing, a.play, idle))
    s.notation(staves, measures, a.time or p.time, keys, clefs)
    for i in range(a.pages):
        s.notation_measure(i * measures)             # also redraws the status box
        s.png("%s-%d.png" % (a.png, i))
        print("%s-%d.png: measures %d-%d" % (a.png, i, i * measures + 1, (i + 1) * measures))
        if i == 0 and a.prn:
            data = s.hardcopy()
            with open(a.prn, "wb") as f:
                f.write(data)
            print("%s: %d bytes printed (tools/print_render.py %s OUT.png --raw)" % (a.prn, len(data), a.prn))
            s.type("\x18")                      # CTRL-X: redraw (mister/README.md)
    return 0


# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="record a piece and save it as .SQnDATA")
    r.add_argument("piece", help=".mid or note list .txt")
    r.add_argument("--w0", required=True, help="SYN-5.3 W0 image (tools/w0_image.py)")
    r.add_argument("--slot", type=int, default=1, help="sequence button 0-7 (.SQnDATA); default 1")
    r.add_argument("--sseq", required=True, help="output sequence file")
    r.add_argument("--parts", help="parts to record, e.g. 1,2,4 (default all)")
    r.add_argument("--beat-ms", type=int, help="click rate in ms (default: the piece's)")
    r.add_argument("--timbre", default="1-2", help="BANK-ENTRY recalled first (default 1-2)")
    r.add_argument("--offset-ms", type=int, default=OFFSET_MS)
    v = sub.add_parser("view", help="recall a sequence in the simulator: Music Notation PNGs, playback")
    v.add_argument("--w0", required=True)
    v.add_argument("--w1", help="W1 image (e.g. from tools/timbre_disk.py --seq)")
    v.add_argument("--catalog", help="make this the current catalog first, e.g. W1:DEMOS")
    v.add_argument("--slot", type=int, required=True)
    v.add_argument("--piece", help="note list: staves, time, keys, clefs and measures from it")
    v.add_argument("--staves", type=int)
    v.add_argument("--time")
    v.add_argument("--keys", help="per staff, e.g. G,G")
    v.add_argument("--clefs", help="per staff, e.g. G,F (A alto, T tenor)")
    v.add_argument("--measures", type=int, help="measures per screen")
    v.add_argument("--pages", type=int, default=1, help="screens to save (Measure# 0, M, 2M, ...)")
    v.add_argument("--png", required=True, help="PNG path prefix: PREFIX-0.png, ...")
    v.add_argument("--play", type=float, default=0, help="play this many seconds, count FM writes")
    v.add_argument("--print", dest="prn", help="Music Notation hardcopy (H) of the first page to this file")
    s = sub.add_parser("show", help="list a sequence file's header and notes")
    s.add_argument("sseq")
    c = sub.add_parser("convert", help="Standard MIDI File -> note list")
    c.add_argument("mid")
    c.add_argument("txt")
    c.add_argument("--split", help="parts holding two voices to split, e.g. 1,2")
    c.add_argument("--shift", type=Fraction, default=0, help="move all notes this many beats later")
    c.add_argument("--beat-ms", type=int, help="click rate in ms (default: the file's tempo)")
    a = ap.parse_args(argv)
    if a.cmd == "view":
        return view(a)
    if a.cmd == "show":
        W = words(open(a.sseq, "rb").read())
        print(seq_header(W))
        for trk, t, k, d in seq_notes(W):
            print("track %2d  %7d ms  %-4s %5d ms" % (trk, t, note_name(k), d))
        return 0
    if a.cmd == "convert":
        piece = read_midi(a.mid)
        if a.split:
            todo = {int(x) - 1 for x in a.split.split(",")}
            piece.parts = [v for i, part in enumerate(piece.parts)
                           for v in (split_voices(part) if i in todo else [part])]
        shift(piece, a.shift)
        if a.beat_ms:
            piece.beat_ms = a.beat_ms
        with open(a.txt, "w", encoding="utf-8") as f:
            write_text(piece, f)
        return 0
    piece = read_piece(a.piece)
    if a.beat_ms:
        piece.beat_ms = a.beat_ms
    if not 0 <= a.slot <= 7:
        ap.error("--slot is 0-7")
    parts = [int(x) - 1 for x in a.parts.split(",")] if a.parts else None
    bank, entry = (int(x) for x in a.timbre.split("-"))
    record(piece, a.w0, a.slot, a.sseq, parts, bank, entry, offset_ms=a.offset_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
