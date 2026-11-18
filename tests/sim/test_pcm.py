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


def test_pan_law():
    """Equal power (M23): hard left full, centre -3 dB a side, power constant."""
    from sim.pan_law import PAN_L, PAN_R
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_pan_law.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (PAN_L[0], PAN_R[0]) == (256, 0) and (PAN_L[32], PAN_R[32]) == (181, 181)
    assert all(abs(PAN_L[p] ** 2 + PAN_R[p] ** 2 - 65536) < 400 for p in range(64))


def test_pcm_out_arithmetic():
    """One voice at full level, hard-panned: 1/16 of full scale at FM level
    0 dB (M23), 1/4 at the default +12 dB (#76), each OSD step 6 dB."""
    full = voice.FULL_SCALE
    want = {0: 8192, 1: 16384, 2: 32767, 3: 2048}        # round(32767 x 2**(dB/6) / 16)
    for level, v in want.items():
        p = pcm.PcmOut(level, False)
        frames = [f for f in (p.push(full, -full) for _ in range(pcm.DECIM * 40)) if f]
        assert frames[-1] == (v, -v), (level, frames[-1])
    assert frames[0] != frames[-1]                        # the window fills over 32 frames
    assert pcm._round_shift(5, 1) == 2 and pcm._round_shift(7, 1) == 4 and pcm._round_shift(-5, 1) == -2


def test_render_frames_join():
    """Windows of render_frames that meet equal one call (FIR warm-up), and
    equal PcmOut over the same instants."""
    regs = fm.registers(230, 191, 3)
    log = _sine_log(*regs)
    log.append((12_000_000, 1, voice.FN_LIM, 0))                 # release inside the window
    whole = pcm.render_frames(log, 5_000_000, 25_000_000, voices=1, origin_ns=0)
    parts = (pcm.render_frames(log, 5_000_000, 15_000_000, voices=1, origin_ns=0)
             + pcm.render_frames(log, 15_000_000, 25_000_000, voices=1, origin_ns=0))
    assert len(whole) == 960 and whole == parts
    synth, out, ref, i = voice.FMSynth(1), pcm.PcmOut(), [], 0
    for k in range(25_000_000 * pcm.IN_RATE // 1_000_000_000):
        t = k * 1_000_000_000 // pcm.IN_RATE
        while i < len(log) and log[i][0] <= t:
            synth.write(*log[i])
            i += 1
        f = out.push(*synth.sample_int(t))
        if f is not None and t >= 5_000_000:
            ref.append(f)
    assert ref == whole and max(abs(l) for l, _ in whole) > 1000
    # unlimited (pcm_wide) windows join too, and the limiter over the
    # joined pairs is one limited call
    wide = (pcm.render_frames(log, 5_000_000, 15_000_000, voices=1, origin_ns=0, fm_level=1, limit=None)
            + pcm.render_frames(log, 15_000_000, 25_000_000, voices=1, origin_ns=0, fm_level=1, limit=None))
    assert pcm.limit_frames(wide) == pcm.render_frames(log, 5_000_000, 25_000_000, voices=1,
                                                       origin_ns=0, fm_level=1)


def test_limiter():
    """#76: transparent below -1 dBFS; never above it; holds 20 ms, then
    releases (85 ms time constant); off clips as before."""
    lim = pcm.Limiter()
    quiet = [(int(20000 * math.sin(i / 7)), -int(15000 * math.sin(i / 7))) for i in range(500)]
    assert [lim.step(*v) for v in quiet] == quiet
    loud = [(int(120000 * math.sin(i / 7)), int(60000 * math.sin(i / 5))) for i in range(4000)]
    out = [lim.step(*v) for v in loud]
    assert max(max(abs(l), abs(r)) for l, r in out) == pcm.LIM_T
    g = lim.g
    for _ in range(pcm.LIM_HOLD + 1):
        lim.step(0, 0)
    assert lim.g > g and lim.hold == 0
    for _ in range(48_000):                             # 1 s of silence: back to unity
        lim.step(0, 0)
    assert lim.g == pcm.LIM_ONE and lim.step(1234, -1234) == (1234, -1234)
    off = pcm.Limiter(False)
    assert off.step(120000, -120000) == (32767, -32768) and off.step(-5, 5) == (-5, 5)


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



def test_poly_box():
    """M26: PolyBox averages the poly staircase over each 768 kHz interval,
    x' = 64 x P / 16 for a constant P (P has 4 fraction bits, #82) at 0 dB;
    a boundary inside an interval weights the two values by their ns in it."""
    f0 = pcm.F0_TICK_NS
    box = pcm.PolyBox([16000, 16000, -48000, 112], [0, 80, 80, 80], 0, level=2)     # 0 dB
    assert box.step(0) == (0, 0)                     # the first instant: no interval
    seen = []
    for k in range(1, 40):
        t = k * 1_000_000_000 // pcm.IN_RATE
        seen.append((t, box.step(t)))
    # [0, 1302): boundary 0 at the start, P(0) = (1000, 0) all through
    assert seen[0] == (1302, (64000, 0))
    # the interval holding 9900: P(0) up to 9900, P(1) after: still 1000 / 5
    k = next(i for i, (t, _) in enumerate(seen) if t > f0)
    t1, t0 = seen[k][0], seen[k - 1][0]
    assert seen[k][1][0] == 64000
    want_r = 80 * (t1 - f0) * pcm.RECIP[t1 - t0] >> box.shift
    assert seen[k][1][1] == want_r and 0 < want_r < 320
    # the interval holding 19800: 1000 then -3000
    k = next(i for i, (t, _) in enumerate(seen) if t > 2 * f0)
    t1, t0 = seen[k][0], seen[k - 1][0]
    want = (16000 * (2 * f0 - t0) - 48000 * (t1 - 2 * f0)) * pcm.RECIP[t1 - t0] >> box.shift
    assert seen[k][1][0] == want
    # start(t) resumes a run: the same values as from reset
    again = pcm.PolyBox([16000, 16000, -48000, 112], [0, 80, 80, 80], 0, level=2)
    again.start(seen[9][0])
    assert [again.step(t) for t, _ in seen[10:]] == [x for _, x in seen[10:]]
    # a constant P comes out of the filter as P at 0 dB, 2P at the default
    # +6 dB (#76), and so on
    for level, mul in ((2, 1), (0, 2), (1, 4), (3, 0.5)):
        frames = []
        out, box = pcm.PcmOut(0, False), pcm.PolyBox([6000 << pcm.P_FRAC] * 2000, [-320 << pcm.P_FRAC] * 2000, 0, level)
        for k in range(1, 16 * 100 + 1):
            xl, xr = box.step(k * 1_000_000_000 // pcm.IN_RATE)
            f = out.push(0, 0, xl, xr)
            if f:
                frames.append(f)
        # RECIP is rounded: within 1 LSB per doubling
        assert all(abs(g - w) <= max(1, mul) for g, w in zip(frames[-1], (6000 * mul, -320 * mul))), \
            (level, frames[-1])
        if level == 2:
            assert frames[-1] == (6000, -320)


def _tone_db(frames, f, side=0):
    """Level of frequency f in 16-bit frames, dB re full scale (Hann)."""
    n = len(frames)
    re = im = 0.0
    for i, fr in enumerate(frames):
        w = 0.5 - 0.5 * math.cos(2 * math.pi * i / n)
        a = 2 * math.pi * f * i / RATE
        re += w * fr[side] * math.cos(a)
        im += w * fr[side] * math.sin(a)
    return 20 * math.log10(max(1e-9, 4 * math.hypot(re, im) / n / 32768))


def test_poly_aliasing():
    """M26: a voice stepping at F0 (101 kHz) plays a 17 kHz sine; its DAC
    staircase has an image at F0 - 17 kHz = 84.0 kHz. Point-sampled at
    48 kHz (the mix before M26) that image folds to 96 - 84.0 = 12.0 kHz;
    through PolyBox and the FIR it does not."""
    from sim.devices.poly import F0_TICK_NS, PolySynth
    f, n_words = 17_000, 20_000
    f0 = 1e9 / F0_TICK_NS
    p = PolySynth(4, 256)
    p.write(0o155, 0)
    words = [int(round(16000 * math.sin(2 * math.pi * f * i / f0))) & 0xFFFF for i in range(n_words)]
    for fc, vals in ((16, [0, 0] + words), (33, [4095] * 7), (40, [4095] * 4)):
        p.write(0o156, fc)
        for w in vals:
            p.write(0o157, w)
    neg = -n_words & 0xFFFFFFF
    p.write(0o156, 0)
    for w in (neg >> 8 & 0xFFFF, (neg >> 24) << 8 | neg & 0xFF, 0, 0, neg >> 8 & 0xFFFF,
              (neg >> 24) << 8 | neg & 0xFF, 0, 1, 255, 0, 3):     # loop all of it, INC = MOD
        p.write(0o157, w)
    p.record()
    t_end = 120_000_000
    p.tick(t_end)
    p.advance()
    m0, pl = p.out_m0, p.out_l
    # new: the M26 path (100 ms from 20 ms)
    new = pcm.render_frames([], 20_000_000, t_end, voices=1, origin_ns=0, poly=(m0, pl, p.out_r),
                            poly_level=2)                           # 0 dB, as before #76
    # old: the DAC staircase point-sampled at the 48 kHz instants
    old = []
    for k in range(960, 960 + len(new)):
        t = k * 1_000_000_000 // RATE
        x = pl[t // F0_TICK_NS + 1 - m0] >> pcm.P_FRAC if t // F0_TICK_NS + 1 - m0 < len(pl) else 0
        old.append((max(-32768, min(32767, x)), 0))
    alias = 2 * RATE - (f0 - f)
    tone_new, tone_old = _tone_db(new, f), _tone_db(old, f)
    alias_new, alias_old = _tone_db(new, alias), _tone_db(old, alias)
    print("  17 kHz: old %.1f dBFS, alias %.1f; new %.1f dBFS, alias %.1f"
          % (tone_old, alias_old, tone_new, alias_new))
    assert abs(tone_new - tone_old) < 1.0                # the tone keeps its level (ZOH droop)
    assert alias_old - tone_old > -20                    # before: the image folds in at ~ -14 dB
    assert alias_new - tone_new < -70                    # after: filtered out

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
