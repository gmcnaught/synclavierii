"""Audio output stage: the FM voice engine's 768 kHz sums, plus the poly
output averaged over each 768 kHz interval (PolyBox, M26), to 48 kHz 16-bit
PCM (hdl/dev/poly_box.sv and pcm_out.sv, bit for bit).

The voice cards' DACs change at each voice's step rate (256 x f) and the
analog stages filter the staircase. Sampling it at 192 kHz and averaging 4
samples (before M23) let the staircase images alias into the audio band at
about -50 to -60 dB; at 768 kHz with this filter the worst in-band spur is
-71 to -77 dB, the same as the staircase filtered without sampling
(docs/tuning-references.md).

Per input sample x (sample_int's integer sum, 1.0 of one voice =
voice.FULL_SCALE = 2**31) and poly part p (PolyBox):
  x' = sat27((x >> IN_SHIFT) + p)                 (floor; |x >> IN_SHIFT| < 2**23 for 32 voices)
every DECIM inputs, with the newest at n:
  acc = sum(COEFFS[j] x x'[n - j], j = 0 .. TAPS-1)   (x' = 0 before the first)
  v   = round_half_even(acc x 32767 / 2**(SUM_BITS + 35 - IN_SHIFT))
  pcm = Limiter (OSD Limiter On, the default) or clip(v) (Off)
At 0 dB (IN_SHIFT = 14) one voice at full level, hard-panned, is 1/16 of
full scale (M23; at 1/4 a dense 32-voice organ chorale clipped 2.25 % of
samples). The OSD FM level and Poly level (#76) shift the two parts before
they are summed: x' = sat27((x >> fm_shift) + p), fm_shift = 14 - dB/6;
the poly part's shift is POLY_SHIFT - dB/6. Defaults: FM +12 dB (one voice
1/4), poly +6 dB, limiter on (docs/poly-output.md 4).
"""
from .pcm_fir import COEFFS, SUM_BITS, TAPS

DECIM = 16                      # 768 kHz -> 48 kHz
IN_RATE = 48_000 * DECIM
IN_SHIFT = 14                                 # FM at 0 dB
OUT_SHIFT = SUM_BITS + 35 - IN_SHIFT          # 41: one voice 1/16 at 0 dB

#: OSD level codes (status bits, 0 = the first option = the default) to dB
#: (#76): FM level +12/+18/+24/0 dB, Poly level +6/+12/0/-6 dB. Whole 6 dB
#: steps, so a level is a shift.
FM_LEVEL_DB = (12, 18, 24, 0)
POLY_LEVEL_DB = (6, 12, 0, -6)


def fm_shift(level=0):
    return IN_SHIFT - FM_LEVEL_DB[level] // 6


def poly_shift(level=0):
    """P carries P_FRAC fraction bits (sim/devices/poly.py, #82)."""
    return POLY_SHIFT + P_FRAC - POLY_LEVEL_DB[level] // 6


#: poly (M26, docs/poly-output.md): sim/devices/poly.py's P(m) holds for
#: [m x F0_TICK_NS, (m + 1) x F0_TICK_NS); PolyBox gives each 768 kHz
#: instant the staircase's average over the interval since the previous
#: instant, scaled so that at 0 dB x' = 64 x P / 2**P_FRAC (pcm = the DAC
#: level, as the poly mix had when it was added to the 16-bit output):
#:   x'_poly = (sum of P x ns in the interval) x RECIP[d] >> poly_shift(level)
#: d = the interval in ns: 1302 or 1303 (the first interval after reset
#: may be shorter: RECIP 0, no poly in it).
F0_TICK_NS = 9900
POLY_SHIFT = 20                 # poly at 0 dB, for P in 16-bit units
P_FRAC = 4                      # P's fraction bits (sim/devices/poly.py P_FRAC, #82)
POLY_GAIN = 64
RECIP = {d: round(POLY_GAIN * (1 << POLY_SHIFT) / d) for d in (1302, 1303)}


class PolyBox:
    """hdl/dev/poly_box.sv: poly P(m) to x' contributions at the 768 kHz
    instants. P(m) = (pl[m - m0], pr[m - m0]), 0 outside the arrays.
    State as the HDL has it after reset: previous instant 0, next boundary
    tick 0, current P 0; start(t) puts it where a run of instants from just
    after t would find it. level: the OSD Poly level code."""

    def __init__(self, pl=(), pr=(), m0=0, level=0):
        self.pl, self.pr, self.m0 = pl, pr, m0
        self.shift = poly_shift(level)
        self.t_prev = 0
        self.nb = 0                       # tick of the next boundary
        self.cur = (0, 0)

    def p(self, m):
        j = m - self.m0
        if 0 <= j < len(self.pl):
            return self.pl[j], self.pr[j]
        return 0, 0

    def start(self, t_prev):
        self.t_prev = t_prev
        self.nb = -(-t_prev // F0_TICK_NS)
        self.cur = self.p(self.nb - 1)

    def step(self, t):
        """x' (left, right) for the instant at t ns (after t_prev)."""
        d = t - self.t_prev
        b = self.nb * F0_TICK_NS
        cl, cr = self.cur
        if b < t:
            nl, nr = self.p(self.nb)
            yl = cl * (b - self.t_prev) + nl * (t - b)
            yr = cr * (b - self.t_prev) + nr * (t - b)
            self.cur = nl, nr
            self.nb += 1
        else:
            yl, yr = cl * d, cr * d
        self.t_prev = t
        k = RECIP.get(d, 0)
        return yl * k >> self.shift, yr * k >> self.shift


def _round_shift(p, s):
    """round(p / 2**s), half to even (Python round(), pcm_out.sv)."""
    q = p >> s
    r = p - (q << s)
    half = 1 << (s - 1)
    if r > half or (r == half and q & 1):
        q += 1
    return q


def pcm_wide(acc):
    """The filter sum in 16-bit units, not clipped (pcm_out.sv's output:
    |v| < 2**21 for any 27-bit x')."""
    return _round_shift(acc * 32767, OUT_SHIFT)


def clip16(v):
    return max(-32768, min(32767, v))


def pcm(acc):
    return clip16(pcm_wide(acc))


#: Limiter (hdl/dev/pcm_limit.sv, #76): one gain for both sides,
#: G / 2**24, 0 < G <= 2**24. Per 48 kHz sample (vl, vr) = pcm_wide:
#:   p = max(|vl|, |vr|)
#:   if p x G > T x 2**24:  G = floor(T x 2**24 / p); hold = HOLD   (attack, instant)
#:   out = (v x G + 2**23) >> 24          (|out| <= T: never clips)
#:   then: hold > 0: hold -= 1;  else G = min(2**24, G + ((2**24 - G) >> REL) + 1)
#: T = -1 dBFS; HOLD 20 ms; REL 12: release time constant 4096 samples
#: (85 ms, about 100 dB/s). Off: out = clip16(v), and G, hold reset.
LIM_ONE = 1 << 24
LIM_T = 29204                   # round(32767 x 10**(-1/20))
LIM_HOLD = 960
LIM_REL = 12


class Limiter:
    def __init__(self, on=True):
        self.on = on
        self.g = LIM_ONE
        self.hold = 0

    def step(self, vl, vr):
        if not self.on:
            self.g, self.hold = LIM_ONE, 0
            return clip16(vl), clip16(vr)
        p = max(abs(vl), abs(vr))
        if p * self.g > LIM_T << 24:
            self.g = (LIM_T << 24) // p
            self.hold = LIM_HOLD
        g = self.g
        out = (vl * g + (1 << 23)) >> 24, (vr * g + (1 << 23)) >> 24
        if self.hold:
            self.hold -= 1
        elif g < LIM_ONE:
            self.g = min(LIM_ONE, g + ((LIM_ONE - g) >> LIM_REL) + 1)
        return out


def limit_frames(wide, on=True, reverb=0, reverb_mix=0, reverb_tone=0):
    """16-bit frames for a run of pcm_wide (left, right) pairs from reset,
    through Reverb (OSD Reverb type, mix and tone codes) then the Limiter."""
    lim = Limiter(on)
    if reverb:
        rv = Reverb()
        return [lim.step(*rv.step(l, r, reverb, reverb_mix, reverb_tone)) for l, r in wide]
    return [lim.step(l, r) for l, r in wide]


#: Reverb (hdl/dev/pcm_reverb.sv, OSD Reverb; not on the instrument): an
#: 8-line feedback delay network between pcm_out and the Limiter, constants
#: from tools/gen_pcm_reverb.py (sim/pcm_reverb.py). Per 48 kHz sample
#: (vl, vr) = pcm_wide, type t (0 Off, 1 Room, 2 Hall, 3 Plate), mix code m,
#: tone code n;
#: one delay memory mem[MEM_WORDS] of 20-bit words, a pointer p (decremented
#: each sample), so a line of length L written at p + B is read L samples
#: later at p + B + L (addresses mod MEM_WORDS). mul(a, c) = a x c / 2**15
#: truncated toward zero, rmul = rounded half up, sat(v, n) = clamp to
#: +-(2**(n-1) - 1):
#:   x = sat((vl + vr) >> 2, 20)
#:   high cut, c = TONE[n]:  s0 = s1;  s1 += mul(((x + xp) >> 1) - s1, c)
#:       s2 += mul(((s1 + s0) >> 1) - s2, c);  xp = x;  f = x if c == 2**15 (Full) else s2
#:   d = mem[p + PD_BASE + PRE[t]];  mem[p + PD_BASE] = f
#:   for k in 0..3 (all-pass):  wm = mem[p + AP_BASE[k] + AP_LEN[k]]
#:       w = sat(d + mul(wm, AP_G[k]), 20);  mem[p + AP_BASE[k]] = w;  d = wm - mul(w, AP_G[k])
#:   for i in 0..7:  tri = ph[i] bits 22:8, inverted when bit 23 is set (0 .. 2**15 - 1)
#:       r = p + LINE_BASE[i] + LENS[t][i] + (tri >> 12)
#:       a = mem[r];  y = a + mul(mem[r + 1] - a, (tri & 4095) << 3)
#:       lp[i] = y + mul(lp[i] - y, POLE[t][i]);  ph[i] = (ph[i] + MOD_INC[i]) mod 2**24
#:   h = Hadamard(lp)  (unnormalised fast Walsh-Hadamard, Sylvester order)
#:   for i in 0..7:  mem[p + LINE_BASE[i]] = sat(mul(h[i], GAINS[t][i]) + SIGN[i] x (d >> 1), 20)
#:   tonal correction:  el = h[1] - mul(hl, TC[t]);  er = h[2] - mul(hr, TC[t]);  hl, hr = h[1], h[2]
#:   out = sat(vl + rmul(el, MIX[t][m]), 22), sat(vr + rmul(er, MIX[t][m]), 22)
#:   p -= 1
#: Off: out = (vl, vr). A change of type to Room/Hall/Plate (or the first
#: sample after reset in one) clears the memory, lp, xp, s1, s2, hl, hr and p, sets
#: ph = MOD_PH0, and the next
#: CLEAR samples (this one included) pass dry while the HDL clears.
def _mul(a, c):
    p = a * c
    return p >> 15 if p >= 0 else -((-p) >> 15)


def _sat(v, bits):
    lim = (1 << (bits - 1)) - 1
    return lim if v > lim else -lim if v < -lim else v


def hadamard8(a):
    """Unnormalised 8-point Walsh-Hadamard transform (Sylvester order):
    h[k] = sum((-1)**popcount(j & k) x a[j])."""
    h = list(a)
    s = 1
    while s < 8:
        for i in range(0, 8, 2 * s):
            for j in range(i, i + s):
                h[j], h[j + s] = h[j] + h[j + s], h[j] - h[j + s]
        s *= 2
    return h


class Reverb:
    def __init__(self, tables=None):
        """tables: sim/pcm_reverb.py by default (a stand-in for tests)."""
        from . import pcm_reverb
        self.rv = tables or pcm_reverb
        self.size = pcm_reverb.MEM_WORDS
        self.mem = [0] * self.size
        self.lp = [0] * 8
        self.p = 0
        self.xp = self.s1 = self.s2 = self.hl = self.hr = 0
        self.ph = list(self.rv.MOD_PH0)
        self.kind = 0
        self.clear = 0

    def step(self, vl, vr, kind, mix=0, tone=0):
        rv = self.rv
        if kind != self.kind:
            self.kind = kind
            if kind:
                self.mem = [0] * self.size
                self.lp = [0] * 8
                self.p = 0
                self.xp = self.s1 = self.s2 = self.hl = self.hr = 0
                self.ph = list(rv.MOD_PH0)
                self.clear = rv.CLEAR
        if not kind:
            return vl, vr
        if self.clear:
            self.clear -= 1
            return vl, vr
        m, p, M = self.mem, self.p, self.size
        x = _sat((vl + vr) >> 2, 20)
        c, s0 = rv.TONE[tone], self.s1
        self.s1 += _mul(((x + self.xp) >> 1) - s0, c)
        self.s2 += _mul(((self.s1 + s0) >> 1) - self.s2, c)
        self.xp = x
        d = m[(p + rv.PD_BASE + rv.PRE[kind]) % M]
        m[(p + rv.PD_BASE) % M] = x if c == 1 << 15 else self.s2
        for k in range(4):
            g = rv.AP_G[k]
            wm = m[(p + rv.AP_BASE[k] + rv.AP_LEN[k]) % M]
            w = _sat(d + _mul(wm, g), 20)
            m[(p + rv.AP_BASE[k]) % M] = w
            d = wm - _mul(w, g)
        lp, lens, pole, ph = self.lp, rv.LENS[kind], rv.POLE[kind], self.ph
        for i in range(8):
            tri = (ph[i] >> 8) & 0x7FFF
            if ph[i] >> 23:
                tri ^= 0x7FFF
            r = p + rv.LINE_BASE[i] + lens[i] + (tri >> 12)
            a = m[r % M]
            y = a + _mul(m[(r + 1) % M] - a, (tri & 4095) << 3)
            lp[i] = y + _mul(lp[i] - y, pole[i])
            ph[i] = (ph[i] + rv.MOD_INC[i]) & 0xFFFFFF
        h = hadamard8(lp)
        inj, gains = d >> 1, rv.GAINS[kind]
        for i in range(8):
            u = _mul(h[i], gains[i]) + (inj if rv.SIGN[i] > 0 else -inj)
            m[(p + rv.LINE_BASE[i]) % M] = _sat(u, 20)
        self.p = (p - 1) % M
        tc = rv.TC[kind]
        el, er = h[1] - _mul(self.hl, tc), h[2] - _mul(self.hr, tc)
        self.hl, self.hr = h[1], h[2]
        c = rv.MIX[kind][mix]
        return (_sat(vl + ((el * c + (1 << 14)) >> 15), 22),
                _sat(vr + ((er * c + (1 << 14)) >> 15), 22))


#: taps oldest-first, for a history kept oldest-first (COEFFS[0] = newest)
_RCOEFFS = tuple(reversed(COEFFS))


def fir(history):
    """sum(COEFFS[j] x history[-1 - j]): the filter at the newest entry of an
    oldest-first list (at least TAPS long)."""
    return sum(c * x for c, x in zip(_RCOEFFS, history[-TAPS:]))


X_BITS = 27                     # x' (FM and poly) saturates to 27 bits (poly_box.sv)
X_MAX, X_MIN = (1 << (X_BITS - 1)) - 1, -(1 << (X_BITS - 1))


def x_in(fm, poly=0, fm_level=0):
    """x' for pcm_out: the FM sum >> fm_shift(fm_level) plus the poly part
    (PolyBox), saturated to X_BITS (poly_box.sv)."""
    return max(X_MIN, min(X_MAX, (fm >> fm_shift(fm_level)) + poly))


class PcmOut:
    """pcm_out.sv (after poly_box.sv): push 768 kHz (left, right) integer FM
    sums and the poly x' parts; every DECIM-th push returns a (left, right)
    16-bit frame (pcm_limit.sv's), otherwise None. limit None: the
    unclipped pcm_wide pair instead (pcm_out.sv's), for a Limiter run
    over a whole render later."""

    def __init__(self, fm_level=0, limit=True):
        self.hl = [0] * TAPS          # oldest first; trimmed now and then
        self.hr = [0] * TAPS
        self.count = 0
        self.fm_level = fm_level
        self.lim = None if limit is None else Limiter(limit)

    def push(self, left, right, pl=0, pr=0):
        self.hl.append(x_in(left, pl, self.fm_level))
        self.hr.append(x_in(right, pr, self.fm_level))
        self.count += 1
        if self.count < DECIM:
            return None
        self.count = 0
        if len(self.hl) > 8 * TAPS:
            del self.hl[:-TAPS]
            del self.hr[:-TAPS]
        v = pcm_wide(fir(self.hl)), pcm_wide(fir(self.hr))
        return v if self.lim is None else self.lim.step(*v)


def frames(samples, fm_level=0, limit=True):
    """16-bit frames for a list of integer (left, right) 768 kHz sums."""
    out = []
    p = PcmOut(fm_level, limit)
    for l, r in samples:
        f = p.push(l, r)
        if f is not None:
            out.append(f)
    return out


def write_wav(path, frames_):
    """16-bit stereo 48 kHz WAV of integer frames."""
    import struct
    data = b"".join(struct.pack("<hh", l, r) for l, r in frames_)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, 48_000, 48_000 * 4, 4, 16))
        f.write(b"data" + struct.pack("<I", len(data)) + data)


def _instant(origin_ns, k):
    return origin_ns + k * 1_000_000_000 // IN_RATE


def render_frames(log, start_ns, end_ns, voices=8, origin_ns=None, poly=None,
                  fm_level=0, poly_level=0, limit=True):
    """pcm_out.sv's 16-bit frames for a window of a D162 write log
    (sim/voice.py FMSynth at the 768 kHz instants origin + k x 1e9 // 768000,
    origin = start_ns by default). Frame j is the filter at instant
    k_start + 16j + 15, k_start the first instant at or after start_ns, which
    must begin a group of DECIM. The filter is warmed up over the TAPS
    instants before k_start (the voice state there is rebuilt by replaying
    the log), so windows that meet join into exactly one longer call: a
    long render can be split across processes. poly: (m0, pl, pr), the
    poly output P(m0 + j) = (pl[j], pr[j]) (PolySynth.record), averaged
    over each interval by PolyBox and added before the filter (M26).
    fm_level, poly_level: OSD level codes. limit: the Limiter (True/False)
    from start_ns; None gives pcm_wide pairs, which windows that meet join
    exactly (limit_frames over the joined pairs = one call)."""
    from .voice import FMSynth
    if origin_ns is None:
        origin_ns = start_ns
    k_start = -(-(start_ns - origin_ns) * IN_RATE // 1_000_000_000)
    while _instant(origin_ns, k_start - 1) >= start_ns:
        k_start -= 1
    while _instant(origin_ns, k_start) < start_ns:
        k_start += 1
    if k_start % DECIM:
        raise ValueError("start_ns does not begin a group of %d instants" % DECIM)
    k_end = k_start
    while _instant(origin_ns, k_end) < end_ns:
        k_end += DECIM
    log = sorted(log, key=lambda e: e[0])
    synth = FMSynth(voices)
    out = PcmOut(fm_level, None)
    lim = None if limit is None else Limiter(limit)
    frames = []
    i = 0
    box = None
    if poly is not None:
        m0, pl, pr = poly
        box = PolyBox(pl, pr, m0, poly_level)
        box.start(_instant(origin_ns, k_start - TAPS - 1))
    for k in range(k_start - TAPS, k_end):
        t = _instant(origin_ns, k)
        while i < len(log) and log[i][0] <= t:
            synth.write(*log[i])
            i += 1
        left, right = synth.sample_int(t)
        xl, xr = box.step(t) if box is not None else (0, 0)
        f = out.push(left, right, xl, xr)
        if f is not None and k >= k_start:
            frames.append(f if lim is None else lim.step(*f))
    return frames
