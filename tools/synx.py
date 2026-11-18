#!/usr/bin/env python3
"""Arturia Synclavier V preset banks (`.synx`) -> NED timbre bank files.

  python3 tools/synx.py list BANK.synx
  python3 tools/synx.py dump BANK.synx NAME [--all-frames]
  python3 tools/synx.py verify BANK.synx TEXT_DIR
  python3 tools/synx.py convert BANK.synx -o OUT.stmb [--report OUT.txt] [--regen TEXT_DIR]

A `.synx` is a stored zip of presets (`<library>/<NNNN> - <name>`). A preset is
a Boost text archive (`serialization::archive 10`): length-prefixed parameter
names with normalised values (0-1), then binary blocks, each
`<len> <name> <size> <bytes>`:

* `Partial P Frame F` (P = 1-12, F = 0-50): 448 bytes = 112 float32 LE
    0-15   frame header (see FRAME_HEADER)
    16-39  carrier harmonics 1-24, coefficient taper (coeff_norm)
    40-63  carrier phases 1-24, phase taper (phase_norm)
    64-87  modulator harmonics 1-24 (Synclavier V only; in every enabled
           frame of the 17 NED banks: harmonic 1 = 1, rest 0)
    88-111 modulator phases (always 0 in those frames)
* `__Mapped__N`, `__HW_Mapped__N`: 4 bytes each (controller mapping).

Frame 0 of a partial is the partial's own harmonic set (NED text frame 0).
Mappings [OBS: `verify` against the Synclavier³ text exports of the
"Original NED FM Timbre Libraries", 941 presets in 17 banks; see
docs/timbre-libraries.md "Synclavier V banks"].
"""
import argparse, bisect, glob, os, re, struct, sys, zipfile

FRAME_FLOATS = 112


def _pwl(pts, x):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def _inv(pts, y):
    return _pwl([(b, a) for a, b in pts], y)


# Harmonic coefficient (NED %, 0.1 steps) -> float. Also frame volume.
COEFF_PTS = [(0, 0.0), (8, 0.32), (20, 0.56), (50, 0.80), (100, 1.0)]
# Stored values that sit off the line [OBS: every occurrence, 45 values]
COEFF_QUIRKS = {196: 0.5402812361717224, 197: 0.5422812700271606}
COEFF_TABLE = [COEFF_QUIRKS.get(i, _pwl(COEFF_PTS, i / 10)) for i in range(1001)]

# Phase (degrees, 64 steps of 5.625) -> float
PHASE_PTS = [(0, 0.0), (34, 0.136), (144, 0.356), (180, 0.5), (216, 0.644),
             (326, 0.864), (360, 1.0)]
PHASE_TABLE = [_pwl(PHASE_PTS, k * 5.625) for k in range(64)]

# Time (s) -> float, frame delay and splice time. Checked to 17.25 s; the
# slope above 10 s is extrapolated beyond that.
TIME_PTS = [(0, 0.0), (0.05, 0.2), (0.1, 0.3), (0.2, 0.38), (0.5, 0.5),
            (1, 0.6), (2, 0.68), (4, 0.76), (10, 0.88), (25, 1.0)]


def _sorted(table):
    pairs = sorted((v, i) for i, v in enumerate(table))
    return [v for v, _ in pairs], [i for _, i in pairs]


def _nearest(st, x):
    vals, idx = st
    i = bisect.bisect_left(vals, x)
    if i == len(vals) or (i > 0 and x - vals[i - 1] <= vals[i] - x):
        i -= 1
    return idx[i]


_COEFF_SORTED = _sorted(COEFF_TABLE)   # not monotonic at 19.6/19.7
_PHASE_SORTED = _sorted(PHASE_TABLE)


def coeff(x):
    """Stored float -> coefficient in % (0.1 resolution)."""
    return _nearest(_COEFF_SORTED, x) / 10


def phase(x):
    """Stored float -> phase in degrees (multiple of 5.625)."""
    return _nearest(_PHASE_SORTED, x) * 5.625


def time_s(x):
    return round(_inv(TIME_PTS, x), 3)


# Frame header floats 0-15. Unlisted indices are constant in the 17 NED
# banks (3 and 7 = 1.0, 9 and 11-15 = 0.0); meaning unknown.
FRAME_HEADER = {
    0: ("enable", lambda x: int(x)),
    1: ("delay_s", time_s),                       # TFPIDelay
    2: ("splice_s", time_s),                      # TFPISpliceTime
    4: ("pitch_semitones", lambda x: round((x - 0.5) * 96)),   # TFPIPitchC
    5: ("pitch_cents", lambda x: round((x - 0.5) * 250)),      # TFPIPitchF
    6: ("volume_pct", coeff),                     # TFPIVolume
    8: ("loop_end", lambda x: int(x)),            # set on the loop-end frame
    10: ("loop_start", lambda x: round(x * 50)),  # PTPIFrameLoopStart
}


class Frame:
    def __init__(self, floats):
        self.raw = floats
        self.header = {name: f(floats[i]) for i, (name, f) in FRAME_HEADER.items()}
        self.coeffs = [coeff(x) for x in floats[16:40]]
        self.phases = [phase(x) for x in floats[40:64]]
        self.modulator = list(floats[64:112])


class Preset:
    def __init__(self, name, data):
        self.name = name
        i = data.index(b" 17 Partial 1 Frame 0 ")
        self.text = data[:i].decode("latin1")
        self.blocks = {}
        p = i + 1
        while p < len(data) - 1:
            m = re.match(rb"(\d+) ", data[p:p + 12])
            n = int(m.group(1)); p += m.end()
            bname = data[p:p + n].decode("latin1"); p += n + 1
            m = re.match(rb"(\d+) ", data[p:p + 12])
            size = int(m.group(1)); p += m.end()
            self.blocks[bname] = data[p:p + size]; p += size + 1
        self.frames = {}
        for bname, raw in self.blocks.items():
            m = re.fullmatch(r"Partial (\d+) Frame (\d+)", bname)
            if m:
                self.frames[(int(m.group(1)) - 1, int(m.group(2)))] = Frame(
                    struct.unpack("<%df" % FRAME_FLOATS, raw))

    def params(self):
        """Normalised parameters: {name: float}. Names are length-prefixed."""
        toks, out, k = self.text.split(" "), {}, 0
        while k < len(toks) - 2:
            if toks[k].isdigit():
                L, name, q = int(toks[k]), "", k + 1
                while q < len(toks) and len(name) < L:
                    name = (name + " " + toks[q]) if name else toks[q]; q += 1
                if (len(name) == L and q < len(toks) and re.match(r"[A-Za-z_]", name)
                        and re.fullmatch(r"-?[0-9.]+(e[-+]?\d+)?", toks[q])):
                    out[name] = float(toks[q]); k = q + 1; continue
            k += 1
        return out


def read_bank(path):
    with zipfile.ZipFile(path) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            if info.is_dir():
                continue
            yield Preset(os.path.basename(info.filename), z.read(info))


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().rstrip("*"))


def _text_entry(path):
    lines = open(path, encoding="latin1").read().splitlines()
    co, tf = {}, {}
    for line in lines:
        s = line.split()
        if not s:
            continue
        if s[0] in ("SynclavierPTCarrierCoeffs", "SynclavierPTCarrierPhases"):
            co[(s[0][-6:], int(s[1]), int(s[2]))] = [float(x) for x in s[4:4 + int(s[3])]]
        elif s[0].startswith("SynclavierTFPI"):
            tf[(s[0][14:], int(s[1]), int(s[2]))] = float(s[4])
    return lines[0], co, tf


TF_FIELDS = {"Delay": ("delay_s", 0.0, 0.0011), "SpliceTime": ("splice_s", 1.0, 0.0011),
             "PitchC": ("pitch_semitones", 0, 0.5), "PitchF": ("pitch_cents", 0, 0.5),
             "Volume": ("volume_pct", 100.0, 0.051)}


def _compare(preset, co, tf):
    n, bad = 0, []
    for (kind, p, fr), vals in co.items():
        f = preset.frames[(p, fr)]
        got = f.coeffs if kind == "Coeffs" else f.phases
        tol = 0.051 if kind == "Coeffs" else 0.01
        for k, v in enumerate(vals):
            n += 1
            if abs(got[k] - v) > tol:
                bad.append((kind, p, fr, k + 1, v, got[k]))
    frames = {(p, fr) for (_, p, fr) in co if fr > 0}
    for p, fr in frames:
        for key, (field, default, tol) in TF_FIELDS.items():
            v = tf.get((key, p, fr), default)
            if key in ("Delay", "SpliceTime") and v > 17.25:
                continue
            n += 1
            got = preset.frames[(p, fr)].header[field]
            if key in ("Delay", "SpliceTime") and v > 10:
                tol = 0.01      # 10.378 s is stored as 10.372 s
            if abs(got - v) > tol:
                bad.append((key, p, fr, 0, v, got))
    return n, bad


def cmd_verify(bank, text_dir):
    texts = {}
    for f in glob.glob(os.path.join(text_dir, "*-Entry.txt")):
        name, co, tf = _text_entry(f)
        texts.setdefault(_norm(name), []).append((os.path.basename(f), co, tf))
    total = mism = paired = unpaired = 0
    for pr in read_bank(bank):
        cands = texts.get(_norm(pr.name.split(" - ", 1)[-1]))
        if not cands:
            unpaired += 1
            print("no text entry: %s" % pr.name)
            continue
        # Several entries may share a name: take the best agreement.
        best = min(((_compare(pr, co, tf), fn) for fn, co, tf in cands),
                   key=lambda r: len(r[0][1]) - r[0][0] * 1e-9)
        (n, bad), fn = best
        paired += 1; total += n; mism += len(bad)
        for b in bad[:4]:
            print("%s (%s): %s partial %d frame %d #%d text %s synx %s" % ((pr.name, fn) + b))
    print("%d presets paired, %d unpaired; %d values, %d differ" % (paired, unpaired, total, mism))
    return 1 if mism else 0


def cmd_list(bank):
    for pr in read_bank(bank):
        used = sorted({p for (p, fr), f in pr.frames.items() if f.header["enable"]})
        nfr = {p: sum(1 for (q, fr), f in pr.frames.items() if q == p and f.header["enable"])
               for p in used}
        print("%-32s partials %s" % (pr.name, " ".join("%d:%d" % (p + 1, nfr[p]) for p in used)))


def cmd_dump(bank, name, all_frames):
    for pr in read_bank(bank):
        if _norm(name) not in (_norm(pr.name), _norm(pr.name.split(" - ", 1)[-1])):
            continue
        print(pr.name)
        for (p, fr), f in sorted(pr.frames.items()):
            if not f.header["enable"] and not all_frames:
                continue
            last = max((i for i, c in enumerate(f.coeffs) if c), default=-1)
            print("  partial %d frame %d %s" % (p + 1, fr, f.header))
            print("    coeffs %s" % f.coeffs[:last + 1])
            if any(f.phases[:last + 1]):
                print("    phases %s" % f.phases[:last + 1])
        return 0
    print("not found: %s" % name)
    return 1


# ------------------------------------------------------------ parameters
# Normalised parameter -> physical value, per the plugin's parameter
# definitions (`Synclavier V.xml`: item lists, value = item index / (N - 1);
# `SynclavierTable(...)` tapers are compiled in, breakpoints fitted to the
# Regen text pairs) [OBS].

def _list(n, f):
    return lambda x: f(int(round(x * (n - 1))))


def _steps(spec):
    """[(first value, step, count), ...] -> item values."""
    out = []
    for v0, step, count in spec:
        out += [round(v0 + step * k, 4) for k in range(count)]
    return out


# Sync100PercentList (251 items) and Sync360DegreesList (251 items)
PCT100 = _steps([(0, 0.1, 30), (3, 0.5, 93), (49.5, 0.25, 4), (50.5, 0.5, 93), (97, 0.1, 31)])
DEG360 = _steps([(0, 1, 34), (34, 2, 55), (144, 1, 36), (180, 0, 1), (-179, 1, 35),
                 (-144, 2, 55), (-34, 1, 35)])
assert len(PCT100) == 251 and len(DEG360) == 251

T_TIME = TIME_PTS[:-1] + [(15, 0.92), (30, 1.0)]       # Sync30_000, seconds
T_PCT = COEFF_PTS                                     # Sync100_0, % (volume)
T_IDX = [(x * 10, y) for x, y in COEFF_PTS]           # Sync100_0, index 0-1000
T_HZ = [(0, 0.0), (5, 0.4), (10, 0.6), (20, 0.76), (50, 1.0)]      # Sync50Herz
T_SEMI = [(0, 0.0), (1, 0.4), (5, 0.72), (20, 0.96), (25, 1.0)]    # Sync25_000Semitones


def _tab(pts, nd):
    return lambda x: round(_inv(pts, x), nd)


DEC = {
    "time": _tab(T_TIME, 3), "pct": _tab(T_PCT, 1), "idx": _tab(T_IDX, 0),
    "hz": _tab(T_HZ, 2), "semi": _tab(T_SEMI, 2),
    "decadj": lambda x: round(1 + x / 0.8, 3),          # SyncDecayAdjust
    "db": _list(501, lambda i: None if i == 0 else (i - 500) / 10),
    "pan": _list(127, lambda i: (i - 63) * 1.0),
    "cents": _list(2501, lambda i: (i - 1250) / 10),
    "semis": _list(49, lambda i: float(i - 24)),
    "octave": _list(9, lambda i: 6.875 * 2 ** i),
    "ratio": _list(161, lambda i: i / 10),
    "fine": _list(201, lambda i: (i - 100) / 1000),
    "pct100": _list(251, lambda i: PCT100[i]),
    "deg": _list(251, lambda i: DEG360[i] % 360),
    "note": _list(128, float),
    "bit": lambda x: int(round(x)),
    "vibwave": _list(6, float),
    "tremwave": _list(3, lambda i: float(2 * i)),
}

# Synclavier V partial parameter -> (Regen PTPI key, decoder)
PARTIAL_PARAMS = [
    ("Volume Envelope Delay", "VEnvDelay", "time"),
    ("Volume Envelope Attack", "VEnvAttack", "time"),
    ("Volume Envelope Initial Decay", "VEnvIDecay", "time"),
    ("Volume Envelope Final Decay", "VEnvFDecay", "time"),
    ("Volume Envelope Peak", "VEnvPeak", "pct"),
    ("Volume Envelope Sustain", "VEnvSust", "pct"),
    ("Index Envelope Delay", "IEnvDelay", "time"),
    ("Index Envelope Attack", "IEnvAttack", "time"),
    ("Index Envelope Initial Decay", "IEnvIDecay", "time"),
    ("Index Envelope Final Decay", "IEnvFDecay", "time"),
    ("Index Envelope Peak", "IEnvPeak", "idx"),
    ("Index Envelope Sustain", "IEnvSust", "idx"),
    ("Decay Adjust", "VEnvAdj", "decadj"),
    ("Partial Pitch Track", "Track", "bit"),
    ("Partial Tuning", "Tune", "cents"),
    ("Partial Transpose", "Tran", "semis"),
    ("Partial Octave", "Octave", "octave"),
    ("Partial Chorus", "ChorusC", "ratio"),
    ("Partial Chorus (Fine)", "ChorusF", "fine"),
    ("Partial FM Ratio", "FMRatioC", "ratio"),
    ("Partial FM Ratio (Fine)", "FMRatioF", "fine"),
    ("Partial Pan", "Pan", "pan"),
    ("Vibrato Wave", "VibWave", "vibwave"),
    ("Vibrato Attack", "VibAttack", "time"),
    ("Vibrato Rate", "VibRate", "hz"),
    ("Carrier Depth", "VibCDepth", "semi"),
    ("Vibrato Invert", "VibInvert", "bit"),
    ("Vibrato Quantize", "VibQuant", "bit"),
    ("Vibrato Bias", "VibBias", "bit"),
    ("Tremolo Depth", "TremDepth", "pct100"),
    ("Tremolo Invert", "TremInvert", "bit"),
    ("Tremolo Alternate", "TremAlt", "bit"),
]
# Written only when not at Regen's default, because stmb.py reads their
# presence (stereo/AM mode, PINFO block, keyboard envelope) [OBS: the value
# Synclavier V stores where the Regen text omits the key].
# Regen writes TremSync only as 0 (359 times, never 1): omitted = on.
PRESENCE_PARAMS = [
    ("Tremolo Phase", "TremPhase", "deg", 180.0),
    ("Tremolo Sync", "TremSync", "bit", 1),
    ("Tremolo Wave", "TremWave", "tremwave", 0.0),
    ("Modulator Depth", "VibMDepth", "semi", 0.0),
    ("Keyboard Envelope Start", "KBDStart", "note", 0.0),
    ("Keyboard Envelope In", "KBDIn", "note", 0.0),
    ("Keyboard Envelope Out", "KBDOut", "note", 127.0),
    ("Keyboard Envelope End", "KBDEnd", "note", 127.0),
]
TIMBRE_PARAMS = [
    ("Timbre Chorus", "ChorusC", "ratio"),
    ("Timbre Chorus (Fine)", "ChorusF", "fine"),
    ("Timbre Portamento", "PortOnOff", "bit"),
    ("Portamento Shape", "PortLinExp", "bit"),
    ("Timbre Repeat", "RepOnOff", "bit"),
    ("Timbre Arpeggiate", "ArpOnOff", "bit"),
    ("Pitch Bend Depth", "BendDepth", "semi"),
]
# Rates are written only while their feature is on: where it is off the
# .synx holds the plugin's reset value (5 Hz, 0.1 s), not NED data [OBS:
# 1,803 of 2,344 partials without TremRate in the Regen text hold 0.4].
RATE_PARAMS = [  # (synx name, Regen key, decoder, enabling Regen keys)
    ("Portamento Rate", "PortRate", "time", ("PortOnOff",)),
    ("Timbre Repeat Rate", "RepRate", "hz", ("RepOnOff", "ArpOnOff")),
]
NUM_NED_PARTIALS = 4


def _extent(f):
    """Index of the last harmonic with a level or a phase."""
    return max((i for i in range(24) if f.coeffs[i] or f.phases[i]), default=0)


def to_entry(pr):
    """Preset -> the entry dict stmb.encode_entry takes (Regen text keys).
    Not in a .synx: real-time effects (every preset carries the same 5
    default modulation slots) and the index envelope adjust (IEnvAdj)."""
    prm = pr.params()
    title = pr.name.split(" - ", 1)[-1]
    kv = []

    def put(key, p, fr, vals):
        kv.append((key, p, fr, len(vals) if len(vals) > 1 or key.endswith(("Coeffs", "Phases")) else 0, vals))

    tb = {}
    for sname, key, dec in TIMBRE_PARAMS:
        if sname in prm:
            tb[key] = DEC[dec](prm[sname])
            put("SynclavierTBPI" + key, 0, 0, [tb[key]])
    for sname, key, dec, enable in RATE_PARAMS:
        if any(tb.get(k) for k in enable):
            put("SynclavierTBPI" + key, 0, 0, [DEC[dec](prm[sname])])
    for p in range(NUM_NED_PARTIALS):
        vol = DEC["db"](prm.get("Partial Volume %d" % (p + 1), 0.0))
        if vol is None:
            continue                                    # partial not in use
        f0 = pr.frames[(p, 0)]
        last = _extent(f0)
        put("SynclavierPTCarrierCoeffs", p, 0, f0.coeffs[:last + 1])
        if any(f0.phases[1:last + 1]):
            put("SynclavierPTCarrierPhases", p, 0, f0.phases[:last + 1])
        vals = {}
        for sname, key, dec in PARTIAL_PARAMS:
            vals[key] = DEC[dec](prm["%s %d" % (sname, p + 1)])
        # Synclavier V turns FM off with the partial's F.M. amount (0); the
        # index envelope then holds reset values where NED has none (peak
        # and sustain 1000, final decay 0.1 s) and NED's own values elsewhere
        # (delays, initial decays, attack 3 ms = the FM export's default,
        # stmb.EXPORT_DEFAULTS). NED has index peak and sustain 0 [OBS: all
        # 398 such partials have no index peak or sustain in the Regen text].
        # Inaudible either way.
        if prm.get("Partial Modulation %d" % (p + 1)) == 0.0:
            vals["IEnvPeak"] = vals["IEnvSust"] = 0.0
            if vals["IEnvFDecay"] == 0.1:
                vals["IEnvFDecay"] = 0.0
        for key, v in vals.items():
            put("SynclavierPTPI" + key, p, 0, [v])
        if vals["TremDepth"]:
            put("SynclavierPTPITremRate", p, 0, [DEC["hz"](prm["Tremolo Rate %d" % (p + 1)])])
        for sname, key, dec, default in PRESENCE_PARAMS:
            v = DEC[dec](prm["%s %d" % (sname, p + 1)])
            if v != default:
                put("SynclavierPTPI" + key, p, 0, [v])
        if vol != 0.0:
            put("SynclavierPTPIVolume", p, 0, [vol])
        frames = sorted(fr for (q, fr), f in pr.frames.items()
                        if q == p and fr > 0 and f.header["enable"])
        for fr in frames:
            f = pr.frames[(p, fr)]
            h = f.header
            last = _extent(f)
            put("SynclavierPTCarrierCoeffs", p, fr, f.coeffs[:last + 1])
            if any(f.phases[:last + 1]):
                put("SynclavierPTCarrierPhases", p, fr, f.phases[:last + 1])
            put("SynclavierTFPIEnable", p, fr, [1.0])
            put("SynclavierTFPISpliceTime", p, fr, [h["splice_s"]])
            put("SynclavierTFPIDelay", p, fr, [h["delay_s"]])
            put("SynclavierTFPIVolume", p, fr, [h["volume_pct"]])
            put("SynclavierTFPIPitchC", p, fr, [float(h["pitch_semitones"])])
            put("SynclavierTFPIPitchF", p, fr, [float(h["pitch_cents"])])
            if h["loop_end"]:
                put("SynclavierPTPIFrameLoopMode", p, 0, [1.0])
                put("SynclavierPTPIFrameLoopStart", p, 0, [float(h["loop_start"])])
                put("SynclavierPTPIFrameLoopEnd", p, 0, [float(fr)])
    # Omitted keys (TremSync on) follow the FM text export's defaults.
    return {"title": title, "kv": kv, "export": 3999}


def _stmb():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import stmb
    return stmb


def slot(pr):
    """Bank and entry (0-7) from the preset number `LLBE - name`."""
    m = re.match(r"\d\d(\d)(\d) - ", pr.name)
    return int(m.group(1)) - 1, int(m.group(2)) - 1


class Regen:
    """The Regen text export of the same library, for what a .synx lacks:
    real-time effects (`SynclavierEM*`) and the index envelope adjust
    (`IEnvAdj`)."""
    KEEP_PT = ("SynclavierPTPIIEnvAdj",)

    def __init__(self, text_dir):
        stmb = _stmb()
        self.texts = {}
        for f in sorted(glob.glob(os.path.join(text_dir, "[1-8][1-8]-Entry.txt"))):
            name, co, tf = _text_entry(f)
            self.texts.setdefault(_norm(name), []).append(
                (os.path.basename(f), co, tf, stmb.parse_text(f)))

    def extra(self, kv):
        return [x for x in kv if x[0].startswith("SynclavierEM") or x[0] in self.KEEP_PT]

    def match(self, pr):
        """-> (file name, kv lines to add, note) or (None, [], note)."""
        cands = self.texts.get(_norm(pr.name.split(" - ", 1)[-1]))
        if not cands:
            return None, [], "no Regen entry"
        b, i = slot(pr)
        own = "%d%d-Entry.txt" % (b + 1, i + 1)
        scored = sorted(((len(_compare(pr, co, tf)[1]), fn != own, fn, e)
                         for fn, co, tf, e in cands), key=lambda r: r[:3])
        best = [r for r in scored if r[0] == scored[0][0]]
        fn, e = best[0][2], best[0][3]
        add = self.extra(e["kv"])
        note = None
        if any(self.extra(r[3]["kv"]) != add for r in best[1:]):
            note = "Regen entry ambiguous (%s), took %s" % (", ".join(r[2] for r in best), fn)
        return fn, add, note


def cmd_convert(bank, output, report, min_sectors, regen_dir=None):
    stmb = _stmb()
    regen = Regen(regen_dir) if regen_dir else None
    banks = [[None] * 8 for _ in range(8)]
    lines = []
    for pr in read_bank(bank):
        b, i = slot(pr)
        e = to_entry(pr)
        extra = []
        if regen:
            fn, add, note = regen.match(pr)
            used = {p for k, p, *_ in e["kv"] if k.startswith("SynclavierPT")}
            e["kv"] += [x for x in add if not x[0].startswith("SynclavierPT") or x[1] in used]
            if note:
                extra.append(note)
            if any(x[0].startswith("SynclavierPT") and x[1] not in used for x in add):
                extra.append("IEnvAdj of an unused partial dropped")
        t, notes = stmb.encode_entry(e)
        notes = extra + notes
        banks[b][i] = t
        lines.append("%d%d %-16s %s" % (b + 1, i + 1, t["name"][:16],
                                         "; ".join(notes) if notes else "ok"))
    stride, need = stmb.write_file(output, banks, min_sectors)
    _, _, rb = stmb.read_banks(output)
    for b in range(8):
        for i in range(8):
            assert (stmb.timbre_words(banks[b][i] or stmb.EMPTY)
                    == stmb.timbre_words(rb[b][i])), "read-back mismatch %d%d" % (b + 1, i + 1)
    text = "\n".join(lines)
    if report:
        open(report, "w").write(text + "\n")
    else:
        print(text)
    print("%s: %d sectors (bank stride %d, largest bank %d sectors)"
          % (output, stride * 8, stride, need))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list"); a.add_argument("bank")
    a = sub.add_parser("dump"); a.add_argument("bank"); a.add_argument("name")
    a.add_argument("--all-frames", action="store_true")
    a = sub.add_parser("verify"); a.add_argument("bank"); a.add_argument("text_dir")
    a = sub.add_parser("convert"); a.add_argument("bank")
    a.add_argument("-o", "--output", required=True)
    a.add_argument("--report")
    a.add_argument("--min-sectors", type=int, default=2000)
    a.add_argument("--regen", metavar="TEXT_DIR",
                   help="Regen text export of the same library: adds its real-time "
                        "effects and index envelope adjust (not in a .synx)")
    args = ap.parse_args()
    if args.cmd == "list":
        cmd_list(args.bank); return 0
    if args.cmd == "dump":
        return cmd_dump(args.bank, args.name, args.all_frames)
    if args.cmd == "convert":
        return cmd_convert(args.bank, args.output, args.report, args.min_sectors, args.regen)
    return cmd_verify(args.bank, args.text_dir)


if __name__ == "__main__":
    sys.exit(main())
