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


def test_reverb_tables_are_generated():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_pcm_reverb.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_reverb_off_is_dry():
    """OSD Reverb Off leaves the samples alone; a change to a type passes
    CLEAR samples dry, then the wet signal starts."""
    from sim.pcm_reverb import CLEAR
    rv = pcm.Reverb()
    ins = [(i * 997 % 4001 - 2000, i * 389 % 3001 - 1500) for i in range(3000)]
    assert [rv.step(l, r, 0) for l, r in ins] == ins
    assert pcm.limit_frames(ins, True, 0) == pcm.limit_frames(ins, True)
    outs = [rv.step(l, r, 2) for l, r in ins]
    assert outs[:CLEAR] == ins[:CLEAR] and outs[CLEAR:] != ins[CLEAR:]


def _edc_t60(ir, lo=-5, hi=-35):
    """T60 from the Schroeder backward integral between lo and hi dB."""
    e = [v * v for v in ir]
    s = tot = sum(e)
    edc = []
    for v in e:
        edc.append(10 * math.log10(max(s, 1e-30) / tot))
        s -= v
    t1 = next(i for i, v in enumerate(edc) if v <= lo)
    t2 = next(i for i, v in enumerate(edc) if v <= hi)
    return (t2 - t1) / RATE * 60 / (lo - hi)


def _lowpass(x, fc):
    """Two one-pole low-passes at fc."""
    a = math.exp(-2 * math.pi * fc / RATE)
    for _ in range(2):
        y, out = 0.0, []
        for v in x:
            y = (1 - a) * v + a * y
            out.append(y)
        x = out
    return x


def _reverb_ir(kind, a, n, tables=None, tone=None):
    """The wet part of each side's response to an impulse a, from the end of
    the clear, mix 0 dB, tone code tone (default Full)."""
    from sim.pcm_reverb import CLEAR, MIX_DB, TONE_HZ
    m0 = MIX_DB.index(0)
    tone = TONE_HZ.index(None) if tone is None else tone
    rv = pcm.Reverb(tables)
    for _ in range(CLEAR):
        rv.step(0, 0, kind, m0, tone)
    wl, wr = [], []
    for k in range(n):
        v = a if k == 0 else 0
        ol, orr = rv.step(v, v, kind, m0, tone)
        wl.append(ol - v)
        wr.append(orr - v)
    return rv, wl, wr


def test_reverb_decay_and_level():
    """Each type's impulse response. Without damping or modulation, the line
    gains give the design T60 (within 10 %); with them, the high band dies
    first. Wet
    energy at mix 0 dB (tone Full) equals the dry impulse's within 0.5 dB,
    the two sides are decorrelated, and the tail settles to within 2 LSB."""
    import types
    from sim import pcm_reverb
    from sim.pcm_reverb import MIX_DB, TONE_HZ
    from tools.gen_pcm_reverb import TYPES
    a = 1 << 18
    undamped = types.SimpleNamespace(**{k: getattr(pcm_reverb, k) for k in dir(pcm_reverb)
                                        if k.isupper()})
    undamped.POLE = ((0,) * 8,) * 4
    undamped.TC = (0,) * 4
    undamped.MOD_INC = undamped.MOD_PH0 = (0,) * 8
    for kind, (name, _pre, _scale, t60, _damp, _mix0) in TYPES.items():
        n = int(RATE * t60)
        _, ul, _ = _reverb_ir(kind, a, n, undamped)
        rv, wl, wr = _reverb_ir(kind, a, n)
        design = _edc_t60(_lowpass(ul, 200))
        broad, high = _edc_t60(wl), _edc_t60([x - y for x, y in zip(wl, _lowpass(wl, 4000))])
        el, er = sum(v * v for v in wl), sum(v * v for v in wr)
        corr = sum(x * y for x, y in zip(wl, wr)) / math.sqrt(el * er)
        for _ in range(int(RATE * 3 * t60)):
            tail = rv.step(0, 0, kind, MIX_DB.index(0), TONE_HZ.index(None))
        print("  %s: T60 %.2f s undamped, unmodulated (design %.2f), %.2f s broadband, %.2f s above 4 kHz; "
              "wet %+.2f dB; L/R correlation %+.3f; tail %s"
              % (name, design, t60, broad, high, 10 * math.log10(el / a ** 2), corr, tail))
        assert abs(design / t60 - 1) < 0.10
        assert high < broad < design
        assert abs(10 * math.log10(el / a ** 2)) < 0.5 and abs(10 * math.log10(er / a ** 2)) < 1.0
        assert abs(corr) < 0.2
        assert max(abs(v) for v in tail) <= 2


def _fft(x):
    """Radix-2 FFT of a list (length a power of 2)."""
    import cmath
    n = len(x)
    if n == 1:
        return list(x)
    ev, od = _fft(x[0::2]), _fft(x[1::2])
    out = [0j] * n
    for k in range(n // 2):
        t = cmath.exp(-2j * math.pi * k / n) * od[k]
        out[k], out[k + n // 2] = ev[k] + t, ev[k] - t
    return out


def _ringing_bins(ir, t60, f1=2000, f2=14000, n=4096):
    """Frequencies (Hz) of the bins in f1..f2 that stand more than 6 dB over
    their 41-bin local median in each of six spectra 0.15 - 0.45 T60 into an
    impulse response (Blackman-Harris, after a first difference): high modes
    that ring on instead of decaying into noise like their neighbours."""
    x = [b - a for a, b in zip(ir, ir[1:])]
    w = [0.35875 - 0.48829 * math.cos(2 * math.pi * i / n) + 0.14128 * math.cos(4 * math.pi * i / n)
         - 0.01168 * math.cos(6 * math.pi * i / n) for i in range(n)]
    b1, b2 = round(f1 * n / RATE), round(f2 * n / RATE)
    hits = None
    for j in range(6):
        c = int((0.15 + 0.06 * j) * t60 * RATE)
        sp = _fft([x[c - n // 2 + i] * w[i] for i in range(n)])
        db = [10 * math.log10(abs(sp[k]) ** 2 + 1e-12) for k in range(b1 - 20, b2 + 21)]
        over = {k for k in range(20, len(db) - 20) if db[k] - sorted(db[k - 20:k + 21])[20] > 6}
        hits = over if hits is None else hits & over
    return sorted(round((k + b1 - 20) * RATE / n) for k in hits)


def test_reverb_jot_damping():
    """Jot's conditions (JOS, PASP 3.7.4-3.7.5): each type's lines add up to
    at least 0.15 T60 x 48000 samples (mode density); every line, gain and
    damping together, decays at the type's T60 at DC (within 1 %) and at
    the same rate as the others at half the sample rate (within 10 %; Jot's
    first-order design). One damping coefficient for every line, as before,
    let Hall's longest line ring on twice as long as its shortest."""
    from sim import pcm_reverb as rv
    from tools.gen_pcm_reverb import TYPES

    def nyquist_t60(n, g, c):
        return -3 * n / (RATE * math.log10(g * c / (2 - c)))

    for kind, (name, _pre, _scale, t60, _alpha, _mix0) in TYPES.items():
        assert sum(rv.LENS[kind]) >= 0.15 * t60 * RATE, name
        ny = []
        for n, g, b in zip(rv.LENS[kind], rv.GAINS[kind], rv.POLE[kind]):
            g, c = g / (1 << 15) * math.sqrt(8), 1 - b / (1 << 15)
            assert abs(-3 * n / (RATE * math.log10(g)) / t60 - 1) < 0.01, (name, n)
            ny.append(nyquist_t60(n, g, c))
        print("  %s: T60 at 24 kHz %.3f - %.3f s across the lines" % (name, min(ny), max(ny)))
        assert max(ny) / min(ny) < 1.10, name
    lens = rv.LENS[2]
    old = [nyquist_t60(n, 10 ** (-3 * n / (2.6 * RATE)), 0.65) for n in lens]
    assert max(old) / min(old) > 1.5


def test_reverb_no_ringing_modes():
    """No high mode rings on in any type's tail (diffuser gains 0.6/0.5, the
    modulated line reads, Jot's damping); the first design (0.75/0.625,
    fixed reads, one damping coefficient a type) did, which the check sees
    in Room."""
    import types
    from sim import pcm_reverb
    from tools.gen_pcm_reverb import TYPES
    a = 1 << 19
    for kind, (name, _pre, _scale, t60, _damp, _mix0) in TYPES.items():
        _, wl, _ = _reverb_ir(kind, a, int(0.45 * t60 * RATE) + 2100)
        bins = _ringing_bins(wl, t60)
        print("  %s: ringing bins %s" % (name, bins))
        assert bins == []
    old = types.SimpleNamespace(**{k: getattr(pcm_reverb, k) for k in dir(pcm_reverb) if k.isupper()})
    old.AP_G, old.MOD_INC, old.MOD_PH0 = (24576, 24576, 20480, 20480), (0,) * 8, (0,) * 8
    old.POLE = ((0,) * 8, (8192,) * 8, (11469,) * 8, (2621,) * 8)   # one damping pole a type
    old.TC = (0,) * 4
    t60 = TYPES[1][3]
    _, wl, _ = _reverb_ir(1, a, int(0.45 * t60 * RATE) + 2100, old)
    bins = _ringing_bins(wl, t60)
    print("  Room, first design: ringing bins %s" % bins)
    assert len(bins) >= 3


def test_reverb_tone():
    """OSD Reverb tone: each code's two stages are 3 dB down at its
    frequency (Full passes x unchanged). The same network follows the high
    cut whatever the code, so on Hall's impulse response the spectrum's
    ratio to Full's, over 1-2 kHz and 10-14 kHz, is the stages' own
    response weighted by Full's spectrum (within 0.5 dB)."""
    from sim.pcm_reverb import Q, TONE, TONE_HZ
    from tools.gen_pcm_reverb import tone_gain2
    for c, fc in zip(TONE, TONE_HZ):
        if fc is None:
            assert c == 1 << Q
            continue
        h2 = tone_gain2(c / (1 << Q), 2 * math.pi * fc / RATE) ** 2
        assert abs(10 * math.log10(h2) + 3) < 0.05, (fc, h2)
    n, frames = 4096, 6
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / n) for i in range(n)]
    bands = [range(f1 * n // RATE, f2 * n // RATE) for f1, f2 in ((1000, 2000), (10000, 14000))]

    def power(code):
        """Per-bin power over the bands, summed over the frames."""
        _, wl, _ = _reverb_ir(2, 1 << 18, n * frames, tone=code)
        p = {k: 0.0 for b in bands for k in b}
        for j in range(frames):
            sp = _fft([v * w for v, w in zip(wl[j * n:(j + 1) * n], win)])
            for k in p:
                p[k] += abs(sp[k]) ** 2
        return p

    full = power(TONE_HZ.index(None))
    for code, fc in enumerate(TONE_HZ):
        if fc is None:
            continue
        p, c = power(code), TONE[code] / (1 << Q)
        got = [10 * math.log10(sum(p[k] for k in b) / sum(full[k] for k in b)) for b in bands]
        want = [10 * math.log10(sum(full[k] * tone_gain2(c, 2 * math.pi * k / n) ** 2 for k in b)
                                / sum(full[k] for k in b)) for b in bands]
        print("  tone %d Hz: 1-2 kHz %+.1f dB (design %+.1f), 10-14 kHz %+.1f dB (design %+.1f)"
              % (fc, got[0], want[0], got[1], want[1]))
        assert all(abs(g - w) < 0.5 for g, w in zip(got, want))


def test_reverb_full_scale_bounded():
    """Full-range noise into Hall at 0 dB mix, tone Full: the output stays
    within the 22 bits pcm_limit takes, and the Limiter holds it under
    -1 dBFS."""
    import random
    from sim.pcm_reverb import TONE_HZ
    full = TONE_HZ.index(None)
    rng = random.Random(3)
    big = (1 << 21) - 1
    wide = [(rng.randrange(-big, big + 1), rng.randrange(-big, big + 1)) for _ in range(20000)]
    rv = pcm.Reverb()
    out = [rv.step(l, r, 2, 3, full) for l, r in wide]
    assert max(abs(v) for f in out for v in f) <= big
    assert max(abs(v) for f in pcm.limit_frames(wide, True, 2, 3, full) for v in f) <= pcm.LIM_T


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
