#!/usr/bin/env python3
"""Recorded pitch of the sample-library sound files, and the patch-list
transposition (PT.TRA) corrections it implies.

    sample_pitch.py scan ROOT [-o data/sample-pitch.tsv] [--jobs N]
    sample_pitch.py check ROOT [--table data/sample-pitch.tsv]

ROOT is the Original-NED-Sample-Patch-Libraries folder (tools/sample_library.py).
`scan` measures the fundamental of every sound file a patch list names and
writes a table (name, measured MIDI key, octave margin, rate); `check` lists
the patch entries the table corrects. tools/sample_library.py applies the
table when it builds the libraries.

Why [OBS, docs/timbre-libraries.md "Patch transpositions"]: SYN-5.3 plays a
patch entry's file at its own sample rate on the key PT.TRA (frame word 10,
low byte = NED key, middle C = 36): 303-SUB3 MRLCH = 2816 + 1024 -
COMPUTE.PATCH.XPOS(PT.TRA) + TOFFS - SRATE, and COMPUTE.PATCH.XPOS equals
COMPUTE.KBD.PITCH (190-NEW0), so that key's pitch is the file's recorded
pitch. In the Regen exports the transposition keys follow the file names
read with NED's octave numbers (C3 = middle C), but whole families (PNO,
VLN, HRP, ...) were recorded an octave below that, so they play an octave
low (FULL PIANO A4 = 220 Hz in the simulator).

Measurement: a 16384-point Hann-windowed spectrum from 50 ms into the file,
then subharmonic summation (Hermes 1988: sum over harmonics h = 1-8 of
0.84^(h-1) x the largest magnitude within 1.5 % of h x f0) over the MIDI
semitone grid 21-108. The octave margin is (score of the best key - the
best score an octave above or below) / score of the best key: how clearly
the octave is decided.

A file's key is its measurement when the octave margin is at least
MIN_MARGIN and the pitch class is the name's note (XXX + note + # or N +
octave + rest, e.g. PNOA#540); otherwise its name group's (same prefix and
rest, e.g. PNO?40) octave relation between recorded key and name, when
that group has GROUP_MIN confident files of which GROUP_AGREE agree
(low piano notes, whose fundamental is weak, are decided this way);
otherwise it is unsure and left alone. A patch entry is corrected only
when that key is an exact octave (+-12) from the PT.TRA key (+ PT.TUN
semitones) and its pitch class is the file name's note. PT.TRA's low byte
moves by the 12; its high byte is kept.
"""
import argparse
import cmath
import math
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TABLE = os.path.join(ROOT, "data", "sample-pitch.tsv")
N_FFT = 16384
START_S = 0.05
HARMONICS = 8
WEIGHT = 0.84
TOLERANCE = 0.015
MIN_MARGIN = 0.15
KEY_TO_MIDI = 24                    # NED key 36 (middle C) = MIDI 60
PT_TRA, PT_TUN = 10, 11
NAME_NOTE = re.compile(r"^([A-Z\-]{3})([A-G])([#N])(\d)(.*)$")
GROUP_MIN, GROUP_AGREE = 3, 0.8
PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


# ------------------------------------------------------------- measuring
def _fft(x):
    """In-place iterative radix-2 FFT of a list of complex numbers."""
    n = len(x)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            x[i], x[j] = x[j], x[i]
    size = 2
    while size <= n:
        w = cmath.exp(-2j * math.pi / size)
        half = size // 2
        for start in range(0, n, size):
            wk = 1
            for k in range(start, start + half):
                t = wk * x[k + half]
                x[k + half] = x[k] - t
                x[k] += t
                wk *= w
        size *= 2
    return x


def spectrum(samples, rate):
    """Magnitudes of a Hann-windowed N_FFT spectrum from START_S in."""
    a = int(START_S * rate)
    seg = list(samples[a:a + N_FFT])
    seg += [0] * (N_FFT - len(seg))
    win = [s * (0.5 - 0.5 * math.cos(2 * math.pi * i / (N_FFT - 1))) for i, s in enumerate(seg)]
    X = _fft([complex(v) for v in win])
    return [abs(c) for c in X[:N_FFT // 2]]


def key_scores(mag, rate):
    """{MIDI key: subharmonic-summation score} for keys 21-108."""
    df = rate / N_FFT
    out = {}
    for key in range(21, 109):
        f0 = 440 * 2 ** ((key - 69) / 12)
        s = 0.0
        for h in range(1, HARMONICS + 1):
            f = h * f0
            if f >= rate / 2 - df:
                break
            lo = max(1, int(f * (1 - TOLERANCE) / df))
            hi = min(len(mag) - 1, int(math.ceil(f * (1 + TOLERANCE) / df)))
            s += WEIGHT ** (h - 1) * max(mag[lo:hi + 1])
        out[key] = s
    return out


def measure(samples, rate):
    """(MIDI key, octave margin) of the fundamental, or None if too quiet."""
    a = int(START_S * rate)
    seg = samples[a:a + N_FFT]
    if len(seg) < N_FFT // 4 or max(abs(v) for v in seg) < 200:
        return None
    sc = key_scores(spectrum(samples, rate), rate)
    best = max(sc, key=sc.get)
    alt = max(sc.get(best - 12, 0.0), sc.get(best + 12, 0.0))
    return best, (sc[best] - alt) / sc[best] if sc[best] else 0.0


def caf_samples(data):
    """(samples of the first channel, frame rate) from .caf bytes."""
    from tools.sample_library import _chunks
    c = _chunks(data)
    rate, _fmt, flags, _bpp, _fpp, ch, _bits = struct.unpack(">d4sIIIII", c["desc"][:32])
    pcm = c["data"][4:]
    order = "<" if flags & 2 else ">"
    x = struct.unpack("%s%dh" % (order, len(pcm) // 2), pcm[:len(pcm) // 2 * 2])
    return x[::ch], int(round(rate))


def _scan_one(item):
    name, path = item
    samples, rate = caf_samples(open(path, "rb").read())
    return name, measure(samples, rate), rate


def scan(root, jobs=None):
    """[(name, key or None, margin, rate)] for every sound a patch list names."""
    from multiprocessing import get_context
    from tools.sample_library import bank_sources, caf_index, patch_names
    cafs = caf_index(root)
    names = sorted({s for _f, _b, ts in bank_sources(root) for t in ts if t
                    for s in patch_names(t) if s in cafs})
    items = [(n, cafs[n]) for n in names]
    if jobs == 1:
        res = [_scan_one(i) for i in items]
    else:
        with get_context("spawn").Pool(jobs or os.cpu_count()) as pool:
            res = pool.map(_scan_one, items, chunksize=4)
    return [(n, m[0] if m else None, m[1] if m else 0.0, rate) for n, m, rate in res]


def write_table(rows, path):
    used = resolve(rows)
    with open(path, "w") as f:
        f.write("# tools/sample_pitch.py scan: recorded fundamental of each patch-list sound file\n")
        f.write("# name\tmeasured_key\toctave_margin\trate\tkey\tbasis\n")
        for n, key, margin, rate in rows:
            k, basis = used.get(n, (None, "silent"))
            f.write("%s\t%s\t%.3f\t%d\t%s\t%s\n" % (n, "-" if key is None else key, margin, rate,
                                                     "-" if k is None else k, basis))


def read_table(path=TABLE):
    """{name: (MIDI key, basis)} for files whose key is settled (measured
    or from their name group; "unsure" and silent ones are left out)."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        n, _m, _margin, _rate, key, basis = line.rstrip("\n").split("\t")
        if key != "-" and basis != "unsure":
            out[n] = (int(key), basis)
    return out


# ------------------------------------------------------------ correcting
def name_pitch_class(name):
    m = NAME_NOTE.match(name)
    if not m:
        return None
    return (PITCH_CLASS[m.group(2)] + (1 if m.group(3) == "#" else 0)) % 12


def name_key(name):
    """MIDI key of the file name's note read with standard octaves
    (PNOA#540 -> A#5 = 82), or None."""
    m = NAME_NOTE.match(name)
    if not m:
        return None
    return 12 * (int(m.group(4)) + 1) + name_pitch_class(name)


def name_group(name):
    """Files named alike (prefix + what follows the octave digit, e.g.
    PNO?40): one recording session, one naming convention."""
    m = NAME_NOTE.match(name)
    return m.group(1) + "?" + m.group(5) if m else None


def resolve(rows, min_margin=MIN_MARGIN):
    """Per file: (key used, basis). A confident measurement (octave margin
    >= min_margin, pitch class = the name's note) is used as is. Otherwise
    the file takes its name group's octave relation (recorded key - name
    key), when at least GROUP_MIN confident files of the group give one and
    GROUP_AGREE of them agree, and its own measurement has the name's pitch
    class."""
    from collections import Counter, defaultdict
    rel = defaultdict(Counter)
    for n, key, margin, _rate in rows:
        nk = name_key(n)
        if key is not None and nk is not None and margin >= min_margin and (key - nk) % 12 == 0:
            rel[name_group(n)][key - nk] += 1
    out = {}
    for n, key, margin, _rate in rows:
        nk = name_key(n)
        if key is None:
            continue
        if margin >= min_margin and (nk is None or (key - nk) % 12 == 0):
            out[n] = (key, "measured")
            continue
        c = rel.get(name_group(n)) if nk is not None else None
        if c and (key - nk) % 12 == 0:
            r, k = c.most_common(1)[0]
            tot = sum(c.values())
            if tot >= GROUP_MIN and k >= GROUP_AGREE * tot:
                out[n] = (nk + r, "group %s (%d/%d)" % (name_group(n), k, tot))
                continue
        out[n] = (key, "unsure")
    return out


def correction(name, tra, tun, table):
    """Semitones to add to PT.TRA's key for a patch entry (0 = none) and why."""
    if not tra & 255:
        return 0, "no transposition"
    if name not in table:
        return 0, "not settled"
    key, _basis = table[name]
    s16 = tun - 65536 if tun >= 32768 else tun
    expect = (tra & 255) + KEY_TO_MIDI + round(s16 / 100)
    diff = key - expect
    if diff == 0:
        return 0, "in tune"
    if diff not in (12, -12):
        return 0, "off by %+d (not an octave)" % diff
    pc = name_pitch_class(name)
    if pc is None or pc != key % 12:
        return 0, "name has no matching note"
    if not 0 <= (tra & 255) + diff <= 255:
        return 0, "key out of range"
    return diff, "ok"


def correct_timbre(t, table, log=None):
    """Apply the corrections to a parsed timbre's patch lists in place.
    Returns the number of entries changed."""
    n = 0
    for pt in t["partials"]:
        for f in (pt or {}).get("frames", []):
            if f[1] != 1 or len(f) <= PT_TUN:
                continue
            from tools.stmb import text_name
            name = text_name(f[3:7])
            d, why = correction(name, f[PT_TRA], f[PT_TUN], table)
            if d:
                f[PT_TRA] = (f[PT_TRA] & 0xFF00) | ((f[PT_TRA] & 255) + d)
                n += 1
            if log is not None:
                log.append((t.get("name", ""), name, f[PT_TRA] & 255, d, why))
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="measure every patch-list sound file")
    s.add_argument("root")
    s.add_argument("-o", "--out", default=TABLE)
    s.add_argument("--jobs", type=int)
    c = sub.add_parser("check", help="list the patch entries the table corrects")
    c.add_argument("root")
    c.add_argument("--table", default=TABLE)
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        rows = scan(a.root, a.jobs)
        write_table(rows, a.out)
        print("%s: %d sound files, %d measured" % (a.out, len(rows), sum(1 for r in rows if r[1] is not None)))
        return 0
    from collections import Counter
    from tools.sample_library import bank_sources
    table = read_table(a.table)
    log = []
    for folder, b, ts in bank_sources(a.root):
        for t in ts:
            if t:
                correct_timbre(t, table, log)
    why = Counter(w if not w.startswith("off by") else "off, not an octave" for *_x, w in log)
    files = Counter((name, d) for _t, name, _k, d, w in log if w == "ok")
    print("patch entries %d: %s" % (len(log), ", ".join("%s %d" % kv for kv in why.most_common())))
    print("sound files moved: %d down an octave in pitch (key +12), %d up (key -12)" % (
        len({n for n, d in files if d > 0}), len({n for n, d in files if d < 0})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
