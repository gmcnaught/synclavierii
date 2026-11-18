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
  pcm = clip(round_half_even(acc x 32767 / 2**(SUM_BITS + 35 - IN_SHIFT)))
so one voice at full level, hard-panned, is 1/16 of full scale (M23; it was
1/4, and 32 voices clipped: a dense 32-voice organ chorale clipped 2.25 % of
samples at 1/4 and peaks at -5.6 dBFS at 1/16).
"""
from .pcm_fir import COEFFS, SUM_BITS, TAPS

DECIM = 16                      # 768 kHz -> 48 kHz
IN_RATE = 48_000 * DECIM
IN_SHIFT = 14
OUT_SHIFT = SUM_BITS + 35 - IN_SHIFT          # 41: gain 1/16


#: poly (M26, docs/poly-output.md): sim/devices/poly.py's P(m) holds for
#: [m x F0_TICK_NS, (m + 1) x F0_TICK_NS); PolyBox gives each 768 kHz
#: instant the staircase's average over the interval since the previous
#: instant, scaled so that x' = 64 x P (pcm = P, the level the poly mix had
#: when it was added to the 16-bit output):
#:   x'_poly = (sum of P x ns in the interval) x RECIP[d] >> POLY_SHIFT
#: d = the interval in ns: 1302 or 1303 (the first interval after reset
#: may be shorter: RECIP 0, no poly in it).
F0_TICK_NS = 9900
POLY_SHIFT = 20
POLY_GAIN = 64
RECIP = {d: round(POLY_GAIN * (1 << POLY_SHIFT) / d) for d in (1302, 1303)}


class PolyBox:
    """hdl/dev/poly_box.sv: poly P(m) to x' contributions at the 768 kHz
    instants. P(m) = (pl[m - m0], pr[m - m0]), 0 outside the arrays.
    State as the HDL has it after reset: previous instant 0, next boundary
    tick 0, current P 0; start(t) puts it where a run of instants from just
    after t would find it."""

    def __init__(self, pl=(), pr=(), m0=0):
        self.pl, self.pr, self.m0 = pl, pr, m0
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
        return yl * k >> POLY_SHIFT, yr * k >> POLY_SHIFT


def _round_shift(p, s):
    """round(p / 2**s), half to even (Python round(), pcm_out.sv)."""
    q = p >> s
    r = p - (q << s)
    half = 1 << (s - 1)
    if r > half or (r == half and q & 1):
        q += 1
    return q


def pcm(acc):
    q = _round_shift(acc * 32767, OUT_SHIFT)
    return max(-32768, min(32767, q))


#: taps oldest-first, for a history kept oldest-first (COEFFS[0] = newest)
_RCOEFFS = tuple(reversed(COEFFS))


def fir(history):
    """sum(COEFFS[j] x history[-1 - j]): the filter at the newest entry of an
    oldest-first list (at least TAPS long)."""
    return sum(c * x for c, x in zip(_RCOEFFS, history[-TAPS:]))


X_BITS = 27                     # x' (FM and poly) saturates to 27 bits (poly_box.sv)
X_MAX, X_MIN = (1 << (X_BITS - 1)) - 1, -(1 << (X_BITS - 1))


def x_in(fm, poly=0):
    """x' for pcm_out: the FM sum >> IN_SHIFT plus the poly part (PolyBox),
    saturated to X_BITS (poly_box.sv)."""
    return max(X_MIN, min(X_MAX, (fm >> IN_SHIFT) + poly))


class PcmOut:
    """pcm_out.sv (after poly_box.sv): push 768 kHz (left, right) integer FM
    sums and the poly x' parts; every DECIM-th push returns a (left, right)
    16-bit frame, otherwise None."""

    def __init__(self):
        self.hl = [0] * TAPS          # oldest first; trimmed now and then
        self.hr = [0] * TAPS
        self.count = 0

    def push(self, left, right, pl=0, pr=0):
        self.hl.append(x_in(left, pl))
        self.hr.append(x_in(right, pr))
        self.count += 1
        if self.count < DECIM:
            return None
        self.count = 0
        if len(self.hl) > 8 * TAPS:
            del self.hl[:-TAPS]
            del self.hr[:-TAPS]
        return pcm(fir(self.hl)), pcm(fir(self.hr))


def frames(samples):
    """16-bit frames for a list of integer (left, right) 768 kHz sums."""
    out = []
    p = PcmOut()
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


def render_frames(log, start_ns, end_ns, voices=8, origin_ns=None, poly=None):
    """pcm_out.sv's 16-bit frames for a window of a D162 write log
    (sim/voice.py FMSynth at the 768 kHz instants origin + k x 1e9 // 768000,
    origin = start_ns by default). Frame j is the filter at instant
    k_start + 16j + 15, k_start the first instant at or after start_ns, which
    must begin a group of DECIM. The filter is warmed up over the TAPS
    instants before k_start (the voice state there is rebuilt by replaying
    the log), so windows that meet join into exactly one longer call: a
    long render can be split across processes. poly: (m0, pl, pr), the
    poly output P(m0 + j) = (pl[j], pr[j]) (PolySynth.record), averaged
    over each interval by PolyBox and added before the filter (M26)."""
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
    out = PcmOut()
    frames = []
    i = 0
    box = None
    if poly is not None:
        m0, pl, pr = poly
        box = PolyBox(pl, pr, m0)
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
            frames.append(f)
    return frames
