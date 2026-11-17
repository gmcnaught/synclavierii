"""FM output stage (M23): sim/pcm.py, the 768 kHz -> 48 kHz decimation filter
shared with hdl/dev/pcm_out.sv, and the aliasing it removes."""
import math
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)

from sim import fm, pcm, voice  # noqa: E402
from sim.pcm_fir import COEFFS, SUM_BITS, TAPS  # noqa: E402

RATE = 48_000


def test_tables_are_generated():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_pcm_fir.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_filter_shape():
    assert len(COEFFS) == TAPS and sum(COEFFS) == 1 << SUM_BITS and list(COEFFS) == list(COEFFS)[::-1]

    def gain_db(f):
        re = sum(c * math.cos(2 * math.pi * f / pcm.IN_RATE * n) for n, c in enumerate(COEFFS))
        im = sum(c * math.sin(2 * math.pi * f / pcm.IN_RATE * n) for n, c in enumerate(COEFFS))
        return 20 * math.log10(math.hypot(re, im) / (1 << SUM_BITS))
    assert abs(gain_db(1000)) < 0.01 and abs(gain_db(15000)) < 0.05 and gain_db(18000) > -0.5
    assert gain_db(26000) < -90 and gain_db(60000) < -90


def test_pcm_out_arithmetic():
    """One voice at full level reaches 1/4 of full scale, as before M23."""
    p = pcm.PcmOut()
    full = voice.FULL_SCALE
    frames = [f for f in (p.push(full, -full) for _ in range(pcm.DECIM * 40)) if f]
    assert frames[-1] == (8192, -8192), frames[-1]       # round(32767 / 4)
    assert frames[0] != frames[-1]                        # the window fills over 32 frames
    assert pcm._round_shift(5, 1) == 2 and pcm._round_shift(7, 1) == 4 and pcm._round_shift(-5, 1) == -2


def _sine_log(onu, nnu, inc):
    t = 1000
    log = [(t, 1, voice.FN_TIM, 32), (t, 1, voice.FN_ZMA, 0)]
    log += [(t, 1, voice.FN_MEM, v) for v in voice.SINE_ROM]
    for ch in (0, 1):
        log += [(t, ch, voice.FN_ONU, onu), (t, ch, voice.FN_NNU, nnu), (t, ch, voice.FN_INC, inc)]
    log += [(t, 0, voice.FN_13, 128), (t, 0, voice.FN_LIM, 0), (t, 1, voice.FN_13, 255),
            (t, 1, voice.FN_DIV, 255), (t, 1, voice.FN_ADD, 255), (2000, 1, voice.FN_LIM, 255)]
    return log


def _level_db(x, f, ref):
    """Hann-windowed DFT magnitude at f relative to ref (same window)."""
    n = len(x)
    re = im = 0.0
    for k, v in enumerate(x):
        w = v * (0.5 - 0.5 * math.cos(2 * math.pi * k / (n - 1)))
        re += w * math.cos(2 * math.pi * f * k / RATE)
        im += w * math.sin(2 * math.pi * f * k / RATE)
    return 20 * math.log10(max(math.hypot(re, im), 1e-30) / ref)


def test_staircase_images_do_not_alias():
    """A pure 8-bit sine at 1568 Hz (.STAB-style inc/div 230/191, octave 3):
    at 192 kHz with a 4-sample mean, an image of the 401 kHz step rate
    aliased to about 15.84 kHz at -48 dB; at 768 kHz with the FIR it is
    below -70 dB."""
    regs = fm.registers(230, 191, 3)
    f0 = fm.frequency(*regs)
    log = _sine_log(*regs)
    start, end = 50_000_000, 150_000_000            # 0.1 s after the note settles
    results = {}
    for name, os_ in (("old", 4), ("new", pcm.DECIM)):
        x = [l for l, _ in voice.render(log, start, end, rate=RATE, oversample=os_, voices=1)]
        ref = 10 ** (_level_db(x, f0, 1.0) / 20)
        results[name] = max(_level_db(x, f, ref) for f in range(15780, 15900, 5))
    assert results["old"] > -55, results
    assert results["new"] < -70, results


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
