#!/usr/bin/env python3
"""NED timbre bank files (.NEWDATA / Synclavier³ `*NEWDATA.stmb`).

  python3 tools/stmb.py list FILE.stmb
  python3 tools/stmb.py convert FOLDER -o OUT.stmb [--report OUT.txt]
  python3 tools/stmb.py verify SAMPLE_LIBRARIES_DIR

`convert` turns a folder of Synclavier³ text exports (`NN-Entry.txt`,
N = bank 1-8, entry 1-8; e.g. the "Original NED FM Timbre Libraries") into a
bank file for `tools/w0_image.py --newdata`. `verify` encodes the text of
every (`*NEWDATA.stmb`, `NN-Entry.txt`) pair in a sample-library tree and
compares the result with the binary, field by field.

Format [OBS: NED source, jbemond/Software, see docs/timbre-libraries.md]:
file = 8 banks, stride = length/8 sectors (162-TMB2 FIND.NEW.BANK); a bank =
8 timbre records in sequence (131-SDF2 FIND.TIMBRE); a record = 4 partials
(SUP, or 46 params + frames + optional PINFO), optional TINFO, 8 misc words.
Words are big-endian 16-bit.

Text -> parameter encodings: [OBS] where checked against the pairs (see
`verify`), [INF] where taken from the NED source only.
"""
import argparse, collections, glob, math, os, re, struct, sys

SUP, MOR, PINFO, TINFO = 0xFFFE, 0xFFFF, 0xFFFD, 0xFFFC
NUM_PARAMS, PINFO_LEN, TINFO_LEN, NUM_MISC = 46, 32, 96, 8
SECTOR = 256

PNAMES = (["edelay", "eattack", "eidecay", "efdecay", "epeakl", "esustl",
           "idelay", "iattack", "iidecay", "ifdecay", "ipeakl", "isustl"]
          + ["coef%d" % i for i in range(1, 25)]
          + ["ptuning", "vibwave", "vibrate", "vibdepth", "vibattack",
             "glidebits", "gliderate", "ratio", "decadj", "new_chorus"])

# Template blocks [OBS: most common values in the sample-library pairs]
TINFO_TEMPLATE = ([TINFO, 200, 24, 72, 200, 400, 0, 0] + [0x2020] * 8
                  + [15, 0, 0, 0, 0] * 8 + [0] * (TINFO_LEN - 56))
MISC_TEMPLATE = [0, 0, 0, 0, 0, 0, 1000, 122]


def u16(x):
    return int(x) & 0xFFFF


def s16(x):
    return x - 0x10000 if x >= 0x8000 else x


# ---------------------------------------------------------------- bank I/O

def read_words(path):
    b = open(path, "rb").read()
    return list(struct.unpack(">%dH" % (len(b) // 2), b[: len(b) // 2 * 2]))


def text_name(ws):
    s = bytearray()
    for x in ws:
        s += bytes([x & 255, x >> 8])
    return s.decode("latin1").rstrip("\0 ")


def name_words(name):
    b = name.encode("latin1", "replace")[:16].ljust(16, b" ")
    return [b[i] | (b[i + 1] << 8) for i in range(0, 16, 2)]


def parse_timbre(w, p):
    t = {"start": p, "partials": []}
    for _ in range(4):
        if w[p] == SUP:
            p += 1
            t["partials"].append(None)
            continue
        pt = {"params": w[p:p + NUM_PARAMS], "frames": []}
        p += NUM_PARAMS
        while w[p] == MOR:
            n = w[p + 2]
            if n == 0:
                raise ValueError("zero-length frame at %d" % p)
            pt["frames"].append(w[p:p + n])
            p += n
        if w[p] == PINFO:
            pt["pinfo"] = w[p:p + PINFO_LEN]
            p += PINFO_LEN
        t["partials"].append(pt)
    if w[p] == TINFO:
        t["tinfo"] = w[p:p + TINFO_LEN]
        t["name"] = text_name(t["tinfo"][8:16])
        p += TINFO_LEN
    t["misc"] = w[p:p + NUM_MISC]
    t["end"] = p + NUM_MISC
    return t


def bank_layout(nwords):
    secs = nwords // SECTOR
    if secs >= 24 * 8:
        return secs // 8, 8
    return 24, secs // 24


def read_banks(path):
    w = read_words(path)
    stride, nb = bank_layout(len(w))
    banks = []
    for b in range(nb):
        p, ts = b * stride * SECTOR, []
        for _ in range(8):
            t = parse_timbre(w, p)
            ts.append(t)
            p = t["end"]
        banks.append(ts)
    return w, stride, banks


def timbre_words(t):
    """Serialize a parsed or encoded timbre record."""
    out = []
    for pt in t["partials"]:
        if pt is None:
            out.append(SUP)
            continue
        out += [u16(x) for x in pt["params"]]
        for f in pt.get("frames", []):
            out += [u16(x) for x in f]
        if "pinfo" in pt:
            out += [u16(x) for x in pt["pinfo"]]
    if "tinfo" in t:
        out += [u16(x) for x in t["tinfo"]]
    out += [u16(x) for x in t["misc"]]
    return out


EMPTY = {"partials": [None] * 4, "misc": MISC_TEMPLATE}


def write_file(path, banks, min_sectors=2000):
    """banks: list of 8 lists of up to 8 timbres (None = empty slot)."""
    data = []
    for b in range(8):
        slots = ((banks[b] if b < len(banks) else []) + [None] * 8)[:8]
        ws = []
        for t in slots:
            ws += timbre_words(t or EMPTY)
        data.append(ws)
    need = max(-(-len(ws) // SECTOR) for ws in data)
    stride = max(need, -(-min_sectors // 8))
    out = []
    for ws in data:
        out += ws + [0] * (stride * SECTOR - len(ws))
    with open(path, "wb") as f:
        f.write(struct.pack(">%dH" % len(out), *out))
    return stride, need


# ------------------------------------------------------------- text parsing

def num(x):
    try:
        return float(x)
    except ValueError:
        return x


def parse_text(path):
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    e = {"title": lines[0].strip(), "kv": []}
    for l in lines[2:]:
        f = l.split()
        if len(f) >= 4 and f[0].startswith("Synclavier"):
            e["kv"].append((f[0], int(f[1]), int(f[2]), int(f[3]),
                            [num(x) for x in f[4:]]))
    return e


# ----------------------------------------------------------------- encoding

def ms(s):
    return int(round(s * 1000))


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# Stereo/AM mode (vibwave bits 7-15), modes 0-24 per 301-SUB1 COMPUTE.STEREO.
# Text keys [OBS on pairs]: mode 5 = Alt+Invert+Wave2, 10 = Invert+Sync,
# 11 = Wave2+Sync, 16 = Invert, 21 = Phase+Sync, 22 = Phase, 23 = Phase+
# Invert+Sync. Pedal (1,2) and keyboard (3,4) modes have no distinct text and
# are not recoverable; Wave 4 with Alt [INF] = random (19).
def stereo_mode(kv):
    if not kv.get("TremDepth"):
        return 0
    inv = bool(kv.get("TremInvert"))
    sync = bool(kv.get("TremSync"))
    wave = int(kv.get("TremWave", 0))
    if "TremPhase" in kv:                       # amplitude modulation
        return (23 if inv else 21) + (0 if sync else 1)
    if kv.get("TremAlt"):
        if wave == 4:
            return 19
        return 5 if inv else 6                  # triggered ping-pong
    if inv and "TremSync" not in kv and "TremWave" not in kv:
        return 0                                # [OBS] 17 of 18 pairs: mode 0
    base = 9 if sync else 15                    # periodic: sine
    if wave == 2:
        base += 2                               # square
    return base + (1 if inv else 0)


VIB_WAVE = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 10}   # text -> low 4 bits [OBS]


def encode_partial(kv, coefs, phases):
    g = lambda k, d=0.0: kv.get(k, d)
    w = [0] * NUM_PARAMS
    w[0] = clamp(ms(g("VEnvDelay")), 0, 30000)
    w[1] = clamp(int(round(g("VEnvAttack") * 1000 / 0.5625)), 0, 26667)
    w[2] = clamp(ms(g("VEnvIDecay")), 0, 30000)
    w[3] = clamp(ms(g("VEnvFDecay", 0.1)), 0, 30000)
    w[4] = clamp(int(round(g("VEnvPeak", 100.0) * 10)), 0, 1000)
    w[5] = clamp(int(round(g("VEnvSust") * 10)), 0, 1000)
    w[6] = clamp(ms(g("IEnvDelay")), 0, 30000)
    w[7] = clamp(int(round(g("IEnvAttack") * 1000 / 0.5625)), 0, 26667)
    w[8] = clamp(ms(g("IEnvIDecay")), 0, 30000)
    w[9] = clamp(ms(g("IEnvFDecay")), 0, 30000)
    w[10] = clamp(int(round(g("IEnvPeak"))), 0, 1000)
    w[11] = clamp(int(round(g("IEnvSust"))), 0, 1000)
    if coefs is None:
        coefs = [100.0]                          # fresh-partial default
    for i in range(24):
        c = coefs[i] if i < len(coefs) else 0.0
        ph = phases[i] if phases and i < len(phases) and i > 0 else 0.0
        w[12 + i] = (clamp(int(round(c * 10)), 0, 1000)
                     | ((int(round(ph / 5.625)) & 63) << 10))
    hz = g("Octave", 440.0) * 2 ** ((g("Tran") * 100 + g("Tune")) / 1200)
    pt = clamp(int(round(hz * 10)), 1, 17600)
    w[36] = -pt if kv.get("Track", 1) == 0 else pt
    mode = stereo_mode(kv)
    w[37] = (VIB_WAVE.get(int(g("VibWave")), 0)
             | (0x10 if g("VibInvert") else 0) | (0x20 if g("VibQuant") else 0)
             | (0x40 if g("VibBias") else 0) | (mode << 7))
    w[38] = clamp(int(round(g("VibRate", 5.0) * 100)), 0, 5000)
    w[39] = clamp(int(round(g("VibCDepth") * 100)), 0, 2400)
    w[40] = clamp(int(round(g("VibAttack") / 0.0035)), 0, 9999)
    center = clamp(int(round(g("Pan") / 1.26)), -50, 50)
    depth = clamp(int(round(g("TremDepth") / 2)), 0, 50)
    w[41] = (kv.get("_glide", 0) & 3) | ((center & 0x7F) << 2) | (depth << 9)
    w[42] = (kv.get("_gliderate", 0) & 0x3FF) | (clamp(int(round(g("TremRate") * 10)), 0, 63) << 10)
    w[43] = clamp(int(round((g("FMRatioC", 1.0) + g("FMRatioF")) * 1000)), -9999, 16000)
    w[44] = ((clamp(int(round((g("VEnvAdj", 1.0) - 1) * 1000)), 0, 1000) & 0x3FF)
             | ((int(round((g("IEnvAdj", 1.0) - 1) * 30)) & 63) << 10))
    w[45] = clamp(int(round((g("ChorusC", 1.0) + g("ChorusF")) * 1000)), -9999, 10000)
    return [u16(x) for x in w]


# Timbre frames (resynthesis) [OBS: PRMLITS 197-233; 160-TMB0 CREATE frame;
# 138-PRE1 COMPUTE.ENV.PARAMS.SUB; PARMSOU E.SEG.LIMITS]. 172 words: MOR,
# type 0, length; words 3-7 and 14-17 are recomputed by the RTP on recall
# (written 0); 8 DEL ms, 9 ATK (splice) ms, 10 EXP, 11 RND, 12 PK x10,
# 13 VOL (pre-PINFO partial volume), 18 PDEL cents, 19 LOOP (target frame
# number, stored in the frame that loops back); 20-43 coefficients with
# phase; 44-171 the 256-byte wave table, low byte first, which the RTP
# copies to wave memory at splice time (303-SUB3, 352-SPLC).
FRAME_LEN = 172

# RTP sine table: .STAB-7 SINTABLE.OFFSET [OBS: equals this formula at all
# 256 points in the Synclavier3 W0 image].
SINE = [math.floor(1024 + 1023.5 * math.sin(2 * math.pi * i / 256)) for i in range(256)]


def compute_wave(coefs):
    """198-SYN2 COMPUTE.WAVE with PHASE.INFO=1: 24 coefficient words ->
    256 bytes (0-255)."""
    buf, offset = [0] * 256, 0
    for n, c in enumerate(coefs, 1):
        j, c = (c >> 8) & 0xFC, c & 1023
        if not c:
            continue
        offset += c * 1024 // 2000
        for i in range(256):
            buf[i] += c * SINE[j] // 2000
            j = (j + n) & 255
    mn, mx = min(buf), max(buf)
    pk = max(mx - offset, offset - mn)
    mx, mn = max(mx, offset + pk), min(mn, offset - pk)
    buf, mx = [b - mn for b in buf], mx - mn
    if mx == 0:
        return [128] * 256
    r = mx // 512
    return [(b + r) * 255 // mx for b in buf]


def encode_frame(fkv, coefs, phases, vol, loop):
    g = lambda k, d=0.0: fkv.get(k, d)
    w = [0] * FRAME_LEN
    w[0], w[1], w[2] = MOR, 0, FRAME_LEN
    w[8] = clamp(ms(g("Delay")), 0, 20000)
    w[9] = clamp(ms(g("SpliceTime", 1.0)), 0, 20000)      # 160-TMB0 default 1 s
    w[10] = 0           # EXP: no text key; 0 in 109 of 115 stored resynthesis frames
    w[12] = clamp(int(round(g("Volume", 100.0) * 10)), 0, 1000)
    w[13] = vol
    w[18] = clamp(int(round(g("PitchC") * 100 + g("PitchF"))), -4800, 4800)
    w[19] = loop
    for i in range(24):
        c = coefs[i] if i < len(coefs) else 0.0
        ph = phases[i] if phases and i < len(phases) else 0.0
        w[20 + i] = (clamp(int(round(c * 10)), 0, 1000)
                     | ((int(round(ph / 5.625)) & 63) << 10))
    wave = compute_wave(w[20:44])
    w[44:] = [wave[2 * i] | (wave[2 * i + 1] << 8) for i in range(128)]
    return [u16(x) for x in w]


def encode_pinfo(kv):
    keys = ("Volume", "VibMDepth", "KBDStart", "KBDIn", "KBDOut", "KBDEnd")
    if not any(k in kv for k in keys):
        return None
    p = [0] * PINFO_LEN
    p[0] = PINFO
    p[1] = clamp(int(round(1000 * 10 ** (kv.get("Volume", 0.0) / 20))), 0, 1000)
    p[2] = clamp(int(round(kv.get("VibMDepth", 0.0) * 100)), 0, 2400)
    # Keyboard envelope [OBS on one pair: Start 33, In 72 -> 49, 85, 39, 0]:
    # key = MIDI - 23; slopes are key distances.
    if any(k in kv for k in ("KBDStart", "KBDIn", "KBDOut", "KBDEnd")):
        kin = kv.get("KBDIn", kv.get("KBDStart", 23))
        kst = kv.get("KBDStart", kin)
        kout = kv.get("KBDOut", 108)
        kend = kv.get("KBDEnd", kout)
        p[5] = clamp(int(kin) - 23, 0, 85)
        p[6] = clamp(int(kout) - 23, 0, 85)
        p[7] = clamp(int(kin - kst), 0, 85)
        p[8] = clamp(int(kend - kout), 0, 85)
    return [u16(x) for x in p]


SUPPORTED_PT = {
    "VEnvDelay", "VEnvAttack", "VEnvIDecay", "VEnvFDecay", "VEnvPeak", "VEnvSust",
    "IEnvDelay", "IEnvAttack", "IEnvIDecay", "IEnvFDecay", "IEnvPeak", "IEnvSust",
    "Octave", "Tran", "Tune", "Track", "VibWave", "VibInvert", "VibQuant", "VibBias",
    "VibRate", "VibCDepth", "VibMDepth", "VibAttack", "Pan", "TremDepth", "TremRate",
    "TremInvert", "TremSync", "TremWave", "TremAlt", "TremPhase", "FMRatioC", "FMRatioF",
    "VEnvAdj", "IEnvAdj", "ChorusC", "ChorusF", "Volume", "KBDStart", "KBDIn", "KBDOut",
    "KBDEnd", "VibCurve", "VibLink", "FrameLoopMode", "FrameLoopStart", "FrameLoopEnd"}
# Real-time effects: TINFO words 16-55 = 8 expression inputs x 5 words
# [OBS: PRMLITS TI.RTE; 139-PRE2 PARSUB/RB.LOOK]. Input slots: 0 velocity,
# 1 pressure, 2 pedal 1, 3 pedal 2, 4 mod wheel, 5 ribbon, 6 kbd CV,
# 7 breath. Per slot: partial bits (low 4 normal, next 4 inverted), sampled
# destination bits, continuous destination bits, then the same two for
# inverted sensing. Sampled bits (TIMLITS N.*): 0 VE.ATK 1 VE.IDEC 2 VE.DEL
# 3 HE.ATK 4 HE.IDEC 5 VE.FDEC 6 HE.DEL 7 P.RATE 8 HE.FDEC 9 VIB.ATK
# 10 DYN.ENV; continuous: 0 V.RATE 1 V.DEPTH 2 VE.PKSUS 3 V.MDEPTH 4 S.RATE
# 5 HE.PK 6 HE.SUS 7 S.DEP 8 S.PAN 9 TUNING 10 FMRATIO 11 REPRATE 12 CHORUS
# 13 TVOL.
# Text: `SynclavierEMDestinationFactors 0 <source> <n> <factor per destination
# index>`, factor 1 = normal, -1 = inverted. Mapping [OBS on the pairs unless
# marked]: source 1 -> mod wheel, 2 -> velocity, 3 -> pressure; source 6 is
# the keyboard envelope (carried by the PINFO KBD keys, no RTE bits); source 7
# destination 0 -> velocity slot DYN.ENV. Destination index 0 -> VE.PKSUS,
# 3 -> TUNING, 10 -> VE.ATK; 23 and 26 always occur together in the pairs
# (V.DEPTH and S.DEP) [INF: 23 = V.DEPTH, the usual pressure/mod wheel
# patch]. Other indices are not pinned by any pair and are reported.
RTE_SOURCE = {1: 4, 2: 0, 3: 1}
RTE_DEST = {0: (2, 2), 3: (2, 9), 10: (1, 0), 23: (2, 1), 26: (2, 7)}   # (word, bit)


def encode_rte(kv_em, present=15):
    """[(name, source, factors)] -> (40 TINFO words, notes).
    `ScaleFactors 0 <source> <n> <factor per partial>` gives the slot's
    partial bits (low 4 normal, -1 -> inverted, high 4); it is omitted when
    every existing partial is affected; missing trailing partials count as 1
    [OBS: pairs, partial bits compared within the existing partials]."""
    w = [15, 0, 0, 0, 0] * 8
    notes = []
    for name, src, f in kv_em:
        if name == "ScaleFactors" and src in RTE_SOURCE:
            bits = 0
            for p in range(4):
                x = f[p] if p < len(f) else 1.0
                if x > 0:
                    bits |= 1 << p
                elif x < 0:
                    bits |= 16 << p
            w[5 * RTE_SOURCE[src]] = bits & (present | present << 4)
            continue
        if name != "DestinationFactors":
            if any(f):
                notes.append("RTE %s source %d %s" % (name, src, f))
            continue
        for i, x in enumerate(f):
            if not x:
                continue
            if src == 6:
                continue                               # keyboard envelope: PINFO
            if src == 7 and i == 0 and x > 0:
                w[1] |= 1 << 10                        # velocity -> dynamic envelope
                continue
            if src not in RTE_SOURCE or i not in RTE_DEST:
                notes.append("RTE source %d destination %d (%+g)" % (src, i, x))
                continue
            word, bit = RTE_DEST[i]
            w[5 * RTE_SOURCE[src] + word + (2 if x < 0 else 0)] |= 1 << bit
    return w, notes


SUPPORTED_TF = {"Enable", "SpliceTime", "Volume", "PitchC", "PitchF", "Delay"}


def glide_rate(port_rate):
    """Text PortRate -> gliderate (0-1000). 301-SUB1 COMPUTE.GLIDE steps by
    I = rate^2 / 1000; the text is 10 / I [OBS: 4 pair partials, 498-700,
    exact]. No key: 5.3's value in the pairs, 700."""
    if not port_rate:
        return 700
    i = clamp(int(round(10 / port_rate)), 1, 1000)
    return clamp(math.ceil(math.sqrt(i * 1000)), 0, 1000)


def encode_entry(e):
    """Text entry -> (timbre record, list of unsupported/approximate items)."""
    notes = []
    per = collections.defaultdict(dict)
    coefs, phases, present = {}, {}, set()
    tb = {}
    em = []
    fcoefs, fphases = collections.defaultdict(dict), collections.defaultdict(dict)
    ftf = collections.defaultdict(lambda: collections.defaultdict(dict))
    for k, p, fr, n, v in e["kv"]:
        if k.startswith("SynclavierPT"):
            present.add(p)
        if k.startswith("SynclavierPTPI") and fr == 0:
            per[p][k[14:]] = v[0]
            if k[14:] not in SUPPORTED_PT:
                notes.append("%s p%d" % (k[10:], p))
        elif k == "SynclavierPTCarrierCoeffs" and fr == 0:
            coefs[p] = v
        elif k == "SynclavierPTCarrierPhases" and fr == 0:
            phases[p] = v
        elif k.startswith("SynclavierTBPI"):
            tb[k[14:]] = v[0]
        elif k == "SynclavierPTCarrierCoeffs":
            fcoefs[p][fr] = v
        elif k == "SynclavierPTCarrierPhases":
            fphases[p][fr] = v
        elif k.startswith("SynclavierTFPI"):
            ftf[p][fr][k[14:]] = v[0]
            if k[14:] not in SUPPORTED_TF:
                notes.append("frame %s p%d" % (k[10:], p))
        elif k.startswith("SynclavierTF") or (k.startswith("SynclavierPT") and fr != 0):
            notes.append("timbre frames (%s)" % k[10:])
        elif k.startswith("SynclavierEM"):
            em.append((k[12:], fr, v))
    if tb.get("PortOnOff"):
        for p in per:
            per[p]["_glide"] = 1 | (0 if tb.get("PortLinExp") else 2)
            per[p]["_gliderate"] = glide_rate(tb.get("PortRate"))
        if "PortRate" not in tb:
            notes.append("portamento on without PortRate: rate 700 assumed")
    for k in tb:
        if k not in ("PortOnOff", "PortLinExp", "PortRate", "ChorusC", "ChorusF",
                     "RepOnOff", "RepRate", "ArpOnOff", "BendDepth"):
            notes.append("TB %s=%s" % (k, tb[k]))
    t = {"partials": []}
    for p in range(4):
        if p not in present:
            t["partials"].append(None)
            continue
        kv = per[p]
        pt = {"params": encode_partial(kv, coefs.get(p), phases.get(p)), "frames": []}
        pi = encode_pinfo(kv)
        nfr = max([f for f in fcoefs[p] if f > 0] + [f for f in ftf[p] if f > 0] + [0])
        lp_end = int(kv.get("FrameLoopEnd", 0)) if kv.get("FrameLoopMode") else 0
        if kv.get("FrameLoopMode", 1) not in (0, 1):
            notes.append("frame loop mode %s p%d" % (kv["FrameLoopMode"], p))
        for f in range(1, nfr + 1):
            # No coefficient line = Synclavier3 default [100.0]: a lone 100.0 is
            # never written (0 of 1862 lines), all-zero frames are ("1 0.0").
            loop = int(kv.get("FrameLoopStart", 0)) if f == lp_end else 0
            pt["frames"].append(encode_frame(ftf[p][f], fcoefs[p].get(f, [100.0]),
                                             fphases[p].get(f), pi[1] if pi else 1000, loop))
        if pi:
            pt["pinfo"] = pi
        t["partials"].append(pt)
    ti = list(TINFO_TEMPLATE)
    name = e["title"].rstrip()
    ti[8:16] = name_words(name)
    if "BendDepth" in tb:
        ti[1] = u16(int(round(tb["BendDepth"] * 100)))
    ti[16:56], rn = encode_rte(em, sum(1 << p for p in range(4) if p in present))
    notes += rn
    t["tinfo"] = ti
    misc = list(MISC_TEMPLATE)
    misc[0] = (2 if tb.get("RepOnOff") else 0) | (8 if tb.get("ArpOnOff") else 0)
    if "RepRate" in tb:
        misc[5] = clamp(int(round(tb["RepRate"] * 100)), 0, 5000)
    misc[6] = u16(int(round((tb.get("ChorusC", 1.0) + tb.get("ChorusF", 0.0)) * 1000)))
    t["misc"] = misc
    t["name"] = name
    if len(name) > 16:
        notes.append("name truncated to %r" % name[:16])
    return t, sorted(set(notes))


# ----------------------------------------------------------------- commands

def cmd_list(a):
    w, stride, banks = read_banks(a.file)
    print("%s: %d sectors, bank stride %d" % (a.file, len(w) // SECTOR, stride))
    for b, ts in enumerate(banks):
        for i, t in enumerate(ts):
            n = sum(1 for p in t["partials"] if p)
            if n:
                fr = sum(len(p["frames"]) for p in t["partials"] if p)
                print("  %d%d  %-16s  partials %d  frames %d  words %d"
                      % (b + 1, i + 1, t.get("name", ""), n, fr, t["end"] - t["start"]))


def cmd_convert(a):
    banks = [[None] * 8 for _ in range(8)]
    report = []
    for f in sorted(glob.glob(os.path.join(a.folder, "[1-8][1-8]-Entry.txt"))):
        b, i = int(os.path.basename(f)[0]) - 1, int(os.path.basename(f)[1]) - 1
        e = parse_text(f)
        t, notes = encode_entry(e)
        banks[b][i] = t
        report.append("%d%d %-16s %s" % (b + 1, i + 1, t["name"][:16],
                                          "; ".join(notes) if notes else "ok"))
    stride, need = write_file(a.output, banks, a.min_sectors)
    # Read back: every record must parse to the same words.
    _, _, rb = read_banks(a.output)
    for b in range(8):
        for i in range(8):
            want = timbre_words(banks[b][i] or EMPTY)
            got = timbre_words(rb[b][i])
            assert want == got, "read-back mismatch bank %d entry %d" % (b + 1, i + 1)
    text = "\n".join(report)
    if a.report:
        open(a.report, "w").write(text + "\n")
    else:
        print(text)
    print("%s: %d sectors (bank stride %d, largest bank %d sectors)"
          % (a.output, stride * 8, stride, need))


def cmd_verify(a):
    sys.setrecursionlimit(10000)
    stats = collections.defaultdict(lambda: [0, 0])
    bad = collections.defaultdict(list)
    npairs = 0
    for d in sorted(glob.glob(os.path.join(a.root, "*/"))):
        fs = glob.glob(d + "*NEWDATA.stmb")
        if not fs:
            continue
        try:
            _, _, banks = read_banks(fs[0])
        except (ValueError, IndexError):
            continue
        for b, ts in enumerate(banks):
            for i, t in enumerate(ts):
                tx = os.path.join(d, "%d%d-Entry.txt" % (b + 1, i + 1))
                if not os.path.exists(tx) or not any(t["partials"]):
                    continue
                if t["end"] - t["start"] > 20000:
                    continue
                e = parse_text(tx)
                if e["title"] == "*Unnamed Timbre*":
                    continue                    # exported from non-timbre words
                if any(k == "SynclavierPTPatchListEntry" for k, *_ in e["kv"]):
                    patch = True
                else:
                    patch = False
                enc, _ = encode_entry(e)
                npairs += 1
                for p in range(4):
                    got, want = enc["partials"][p], t["partials"][p]
                    if (got is None) != (want is None):
                        stats["partial present"][1] += 1
                        continue
                    stats["partial present"][0] += 1
                    stats["partial present"][1] += 1
                    if got is None:
                        continue
                    for j in range(NUM_PARAMS):
                        if patch and 12 <= j < 36:
                            continue            # patch partials: no coefficients
                        if patch and j == 43:
                            continue            # patch partials: ratio unused (0)
                        gv, wv = s16(got["params"][j]), s16(want["params"][j])
                        tol = 2 if j in (1, 7) else (1 if j in (0, 2, 3, 6, 8, 9, 40) else 0)
                        ok = abs(gv - wv) <= tol
                        stats[PNAMES[j]][0] += ok
                        stats[PNAMES[j]][1] += 1
                        if not ok:
                            bad[PNAMES[j]].append((os.path.basename(d[:-1]), b + 1, i + 1, p, wv, gv))
                    if "pinfo" in want:
                        gp = got.get("pinfo") or [PINFO] + [0] * 31
                        for j, nm in ((1, "pi_pvol"), (2, "pi_mdep"), (5, "pi_kbdl"), (6, "pi_kbdr"),
                                      (7, "pi_kbdls"), (8, "pi_kbdrs")):
                            wv = s16(want["pinfo"][j])
                            gv = s16(gp[j]) if not (j == 1 and "pinfo" not in got) else 1000
                            ok = gv == wv
                            stats[nm][0] += ok
                            stats[nm][1] += 1
                            if not ok:
                                bad[nm].append((os.path.basename(d[:-1]), b + 1, i + 1, p, wv, gv))
                for j, nm in ((0, "misc_bits"), (5, "misc_rep"), (6, "misc_chorus"), (7, "misc_rte")):
                    gv, wv = s16(enc["misc"][j]), s16(t["misc"][j])
                    if j == 0:
                        gv, wv = gv & 0x0A, wv & 0x0A
                    ok = gv == wv
                    stats[nm][0] += ok
                    stats[nm][1] += 1
                    if not ok:
                        bad[nm].append((os.path.basename(d[:-1]), b + 1, i + 1, -1, wv, gv))
                if "tinfo" in t:
                    ok = s16(enc["tinfo"][1]) == s16(t["tinfo"][1])
                    stats["ti_tbd"][0] += ok
                    stats["ti_tbd"][1] += 1
                    for k in range(8):
                        nm = "ti_rte%d" % k
                        gv, wv = list(enc["tinfo"][16 + 5 * k:21 + 5 * k]), list(t["tinfo"][16 + 5 * k:21 + 5 * k])
                        pm = sum(1 << q for q in range(4) if t["partials"][q])
                        pm |= pm << 4                  # partial bits within existing partials
                        gv[0] &= pm
                        wv[0] &= pm
                        ok = gv == wv
                        stats[nm][0] += ok
                        stats[nm][1] += 1
                        if not ok:
                            bad[nm].append((os.path.basename(d[:-1]), b + 1, i + 1, -1, wv, gv))
                    ok = text_name(enc["tinfo"][8:16]) == t.get("name", "")[:16].rstrip()
                    stats["ti_name"][0] += ok
                    stats["ti_name"][1] += 1
                    if not ok:
                        bad["ti_name"].append((os.path.basename(d[:-1]), b + 1, i + 1, -1, t.get("name"), text_name(enc["tinfo"][8:16])))
    print("%d pairs" % npairs)
    for k, (ok, n) in stats.items():
        flag = "" if ok == n else "   e.g. %s" % (bad[k][:3],)
        print("  %-16s %4d/%4d%s" % (k, ok, n, flag))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("file")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("convert")
    p.add_argument("folder")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--report")
    p.add_argument("--min-sectors", type=int, default=2000)
    p.set_defaults(fn=cmd_convert)
    p = sub.add_parser("verify")
    p.add_argument("root")
    p.set_defaults(fn=cmd_verify)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
