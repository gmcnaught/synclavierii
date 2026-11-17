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


class PcmOut:
    """pcm_out.sv: push 768 kHz (left, right) integer sums; every DECIM-th
    push returns a (left, right) 16-bit frame, otherwise None."""

    def __init__(self):
        self.hl = [0] * TAPS          # newest first
        self.hr = [0] * TAPS
        self.count = 0

    def push(self, left, right):
        self.hl.insert(0, left >> IN_SHIFT)
        self.hl.pop()
        self.hr.insert(0, right >> IN_SHIFT)
        self.hr.pop()
        self.count += 1
        if self.count < DECIM:
            return None
        self.count = 0
        acc_l = sum(c * x for c, x in zip(COEFFS, self.hl))
        acc_r = sum(c * x for c, x in zip(COEFFS, self.hr))
        return pcm(acc_l), pcm(acc_r)


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
