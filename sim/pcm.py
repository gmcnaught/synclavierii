"""FM audio output stage: the voice engine's 768 kHz sums to 48 kHz 16-bit
PCM (hdl/dev/pcm_out.sv, bit for bit).

The voice cards' DACs change at each voice's step rate (256 x f) and the
analog stages filter the staircase. Sampling it at 192 kHz and averaging 4
samples (before M23) let the staircase images alias into the audio band at
about -50 to -60 dB; at 768 kHz with this filter the worst in-band spur is
-71 to -77 dB, the same as the staircase filtered without sampling
(docs/tuning-references.md).

Per input sample x (sample_int's integer sum, 1.0 of one voice =
voice.FULL_SCALE = 2**31):
  x' = x >> IN_SHIFT                              (floor; |x'| < 2**23 for 32 voices)
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


class PcmOut:
    """pcm_out.sv: push 768 kHz (left, right) integer sums; every DECIM-th
    push returns a (left, right) 16-bit frame, otherwise None."""

    def __init__(self):
        self.hl = [0] * TAPS          # oldest first; trimmed now and then
        self.hr = [0] * TAPS
        self.count = 0

    def push(self, left, right):
        self.hl.append(left >> IN_SHIFT)
        self.hr.append(right >> IN_SHIFT)
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


def render_frames(log, start_ns, end_ns, voices=8, origin_ns=None):
    """pcm_out.sv's 16-bit frames for a window of a D162 write log
    (sim/voice.py FMSynth at the 768 kHz instants origin + k x 1e9 // 768000,
    origin = start_ns by default). Frame j is the filter at instant
    k_start + 16j + 15, k_start the first instant at or after start_ns, which
    must begin a group of DECIM. The filter is warmed up over the TAPS
    instants before k_start (the voice state there is rebuilt by replaying
    the log), so windows that meet join into exactly one longer call: a
    long render can be split across processes."""
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
    for k in range(k_start - TAPS, k_end):
        t = _instant(origin_ns, k)
        while i < len(log) and log[i][0] <= t:
            synth.write(*log[i])
            i += 1
        f = out.push(*synth.sample_int(t))
        if f is not None and k >= k_start:
            frames.append(f)
    return frames
