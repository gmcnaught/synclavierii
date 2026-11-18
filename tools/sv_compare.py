#!/usr/bin/env python3
"""Compare Synclavier V captures (tools/sv_capture.py) with the simulator.

  python3 tools/sv_compare.py render RELEASE_L.simg OUT [-j 6] [--only fm,env,chorus]
  sv-venv/bin/python tools/sv_compare.py report SV_DIR SIM_DIR [-o REPORT.md]

`render` writes one single-partial test timbre per test (`NN-Entry.txt`
text, `tools/stmb.py` encoding), puts it in bank 0 of `06-TIMBD` and plays
it through Release L ORK-LM in the simulator (`sim.rtp`, run under pypy3
when available: same output, ~6x faster). `report` measures both sets
(FM index, envelope times and levels, chorus/detune) and prints a table.

Key numbers: Synclavier V MIDI 69 (A 440) = ORK key 45; MIDI 60 = key 36.
"""
import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
try:
    import numpy as np      # analysis only; `render` runs without numpy
except ImportError:
    np = None

ORK_KEY = {"A4": 45, "C4": 36}
F0 = {"A4": 440.0, "C4": 261.6256}


# ------------------------------------------------------------------ tests
# (name, text parameters, note, hold s, release s); text units as in the
# Synclavier3 exports: times in s, VEnv levels 0-100, IEnv levels 0-1000.
def sim_tests(only):
    t = []
    if "fm" in only:
        for p in (5, 10, 25, 50, 100, 200, 500, 1000):
            t.append((f"fm_r1_P{p}_A4", {"IEnvPeak": p, "IEnvSust": p}, "A4", 1.5, 0.3))
        for p in (25, 100, 200):
            t.append((f"fm_r2_P{p}_A4", {"IEnvPeak": p, "IEnvSust": p, "FMRatioC": 2.0},
                      "A4", 1.5, 0.3))
        t.append(("fm_r1_P100_iatt1s_A4", {"IEnvPeak": 100, "IEnvSust": 100,
                                           "IEnvAttack": 1.0}, "A4", 2.0, 0.3))
    if "env" in only:
        for a in (0.1, 0.5, 1.0, 2.0):
            t.append((f"env_att{a:g}s_A4", {"VEnvAttack": a}, "A4", a + 1.0, 0.3))
        t.append(("env_delay0.5s_att0.5s_A4", {"VEnvDelay": 0.5, "VEnvAttack": 0.5}, "A4", 1.8, 0.3))
        for d in (0.25, 1.0):
            for s in (50.0, 25.0):
                t.append((f"env_idec{d:g}s_sus{s:g}_A4", {"VEnvIDecay": d, "VEnvSust": s},
                          "A4", d * 3 + 0.5, 0.3))
        for f in (0.25, 1.0, 2.0):
            t.append((f"env_fdec{f:g}s_A4", {"VEnvFDecay": f}, "A4", 0.8, f * 3 + 0.5))
        t.append(("env_fdec1s_C4", {"VEnvFDecay": 1.0}, "C4", 0.8, 3.5))
        for lvl in (100.0, 50.0, 25.0, 10.0, 2.5):
            t.append((f"env_level{lvl:g}_A4", {"VEnvPeak": lvl, "VEnvSust": lvl}, "A4", 1.5, 0.3))
    if "chorus" in only:
        for c, f in ((1.0, 0.002), (1.0, 0.01), (1.0, 0.05), (2.0, 0.005), (0.5, 0.004)):
            for n in ("A4", "C4"):
                t.append((f"chorus{c:g}_{f:+g}_{n}", {"ChorusC": c, "ChorusF": f}, n, 3.0, 0.3))
        for cents in (-10.0, 10.0):
            t.append((f"tune{cents:+g}c_A4", {"Tune": cents}, "A4", 1.5, 0.3))
    return t


def entry_text(title, kv):
    d = dict(VEnvAttack=0.0, VEnvIDecay=0.0, VEnvFDecay=0.0, VEnvPeak=100.0,
             VEnvSust=100.0, IEnvPeak=0.0, IEnvSust=0.0, FMRatioC=1.0, Octave=440.0)
    d.update(kv)
    lines = [title[:16], "", "SynclavierVirtualInstrumentTimbreVersion000 7 12 24 927 99 10",
             "SynclavierPTCarrierCoeffs 0 0 1 100.0"]
    lines += [f"SynclavierPTPI{k} 0 0 0 {v}" for k, v in d.items()]
    return "\n".join(lines) + "\n"


def bank_file(path, title, kv):
    """One-timbre bank 0, cut to the 49 sectors Release L reads per bank."""
    import stmb
    e = {"title": title[:16], "kv": []}
    tmp = path + ".txt"
    open(tmp, "w").write(entry_text(title, kv))
    e = stmb.parse_text(tmp)
    t, notes = stmb.encode_entry(e)
    banks = [[t] + [None] * 7] + [[None] * 8 for _ in range(7)]
    out, stride, need = stmb.bank_bytes(banks)
    open(path, "wb").write(out[:49 * 256 * 2])
    return notes


def render_one(image, out, test, env_clock=None):
    name, kv, note, hold, rel = test
    bank = os.path.join(out, name + ".stmb")
    notes = bank_file(bank, name, kv)
    py = shutil.which("pypy3") or sys.executable
    if env_clock:   # experiment: override sim.fm.ENV_CLOCK_NS (ns per clock) for this run
        pre = [py, "-c", "import sys, runpy, sim.fm as f; f.ENV_CLOCK_NS = int(sys.argv.pop(1)); "
               "runpy.run_module('sim.rtp', run_name='__main__', alter_sys=True)", str(env_clock)]
    else:
        pre = [py, "-m", "sim.rtp"]
    cmd = pre + [image, "--seconds", "8", "--swap-f0", "06-TIMBD",
           "--bank-file", bank, "--buttons", "bank.0,timb.0", "--keys", str(ORK_KEY[note]),
           "--hold", str(hold), "--release", str(rel),
           "--fm-log", os.path.join(out, name + ".csv"), "--wav", os.path.join(out, name + ".wav")]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="replace")
    ok = r.returncode == 0 and os.path.exists(os.path.join(out, name + ".wav"))
    json.dump({"name": name, "text": kv, "note": note, "hold_s": hold, "release_s": rel,
               "env_clock_ns": env_clock,
               "note_on_s": 0.0, "encode_notes": notes, "ok": ok},
              open(os.path.join(out, name + ".json"), "w"), indent=1)
    tail = [l for l in r.stdout.splitlines() if "[rtp]" in l][-3:]
    return name, ok, tail if ok else (r.stderr.splitlines()[-3:] or tail)


def cmd_render(a):
    os.makedirs(a.out, exist_ok=True)
    todo = [t for t in sim_tests(set(a.only.split(",")))
            if a.force or not os.path.exists(os.path.join(a.out, t[0] + ".wav"))]
    print(f"{len(todo)} renders, {a.jobs} at a time", flush=True)
    with cf.ProcessPoolExecutor(a.jobs) as ex:
        for i, (name, ok, tail) in enumerate(ex.map(render_one, [a.image] * len(todo),
                                                    [a.out] * len(todo), todo,
                                                    [a.env_clock] * len(todo))):
            print(f"[{i + 1}/{len(todo)}] {name} {'ok' if ok else 'FAILED'} {tail[-1] if tail else ''}",
                  flush=True)


# --------------------------------------------------------------- analysis
def load(path):
    import numpy as np
    from scipy.io import wavfile
    sr, d = wavfile.read(path)
    scale = {"i": 2.0 ** (8 * d.dtype.itemsize - 1)}.get(d.dtype.kind, 1.0)
    d = d.astype(np.float64) / scale
    if d.ndim == 1:
        d = d[:, None]
    return sr, d


def mono_power(d):
    return (d ** 2).sum(axis=1)


def envelope_db(d, sr, hop=0.0025):
    """RMS (both channels, pan-independent) in `hop` s windows, dB."""
    import numpy as np
    p = mono_power(d)
    n = int(hop * sr)
    m = len(p) // n
    e = p[:m * n].reshape(m, n).mean(axis=1)
    return np.arange(m) * hop + hop / 2, 10 * np.log10(e + 1e-20)


def onset(t, e, below=40):
    pk = e.max()
    i = int(np.argmax(e > pk - below))
    return t[i]


def harmonics(d, sr, f0, t0, t1, nh=12):
    """Harmonic magnitudes (linear, H1..Hnh) of the channel sum, Hann."""
    import numpy as np
    x = d[int(t0 * sr):int(t1 * sr)].sum(axis=1)
    w = np.hanning(len(x))
    sp = np.abs(np.fft.rfft(x * w))
    df = sr / len(x)
    out = []
    for h in range(1, nh + 1):
        k = int(round(h * f0 / df))
        out.append(sp[max(0, k - 6):k + 7].max())
    return np.array(out) / (w.sum() / 2)


def pm_magnitudes(beta, ratio, nh=12, c=0.0):
    """|harmonics| of sin(th + c + beta*sin(ratio*th)), by FFT of one period.
    c is the carrier's phase relative to the modulator; at integer ratios
    with phase-locked oscillators it changes the harmonic balance (an
    unsigned modulator gives c = beta)."""
    import numpy as np
    n = 4096
    th = 2 * np.pi * np.arange(n) / n
    y = np.sin(th + c + beta * np.sin(ratio * th))
    sp = np.abs(np.fft.rfft(y)) / (n / 2)
    return sp[1:nh + 1]


#: Components below this (dB re the strongest) are compared as equal: the
#: core's 8-bit wave and sine ROM put a quantization floor at -54 to -68 dB.
FIT_FLOOR_DB = -50.0


def _fit_err(m, use, b, ratio, c):
    import numpy as np
    p = pm_magnitudes(b, ratio, len(m), c)
    p = p / p.max()
    fl = FIT_FLOOR_DB
    return np.mean((np.maximum(20 * np.log10(p + 1e-9), fl)
                    - np.maximum(20 * np.log10(m + 1e-9), fl)) ** 2)


def fit_beta(mags, ratio):
    """Least-squares fit (dB, floor FIT_FLOOR_DB) of the PM index beta
    and the carrier phase c (32 steps). Returns (beta, c, rms dB)."""
    import numpy as np
    m = mags / mags.max()
    use = None
    cs = np.arange(32) * np.pi / 16
    best = None
    for b in np.concatenate([np.arange(0, 2, 0.01), np.arange(2, 45, 0.04)]):
        for c in cs:
            e = _fit_err(m, use, b, ratio, c)
            if best is None or e < best[0]:
                best = (e, b, c)
    err, b, c = best
    for bb in np.arange(max(0, b - 0.05), b + 0.05, 0.001):
        for cc in np.arange(c - np.pi / 16, c + np.pi / 16, np.pi / 256):
            e = _fit_err(m, use, bb, ratio, cc)
            if e < err:
                err, b, c = e, bb, cc
    return b, c % (2 * np.pi), err ** 0.5


def peak_freq(d, sr, f, t0, t1, span=0.08):
    """Frequency of the strongest component within f*(1 +- span), zero-padded."""
    import numpy as np
    x = d[int(t0 * sr):int(t1 * sr)].sum(axis=1)
    x = x * np.hanning(len(x))
    nfft = 1 << 22
    sp = np.abs(np.fft.rfft(x, nfft))
    df = sr / nfft
    lo, hi = int(f * (1 - span) / df), int(f * (1 + span) / df)
    k = lo + int(np.argmax(sp[lo:hi]))
    a, b, c = np.log(sp[k - 1:k + 2] + 1e-30)
    return (k + 0.5 * (a - c) / (a - 2 * b + c)) * df


def beat_rate(d, sr, t0, t1):
    """Dominant amplitude-modulation frequency (Hz) of the envelope."""
    import numpy as np
    hop = 0.002
    t, e = envelope_db(d, sr, hop)
    m = (t >= t0) & (t < t1)
    a = 10 ** (e[m] / 20)
    a = a - a.mean()
    if np.abs(a).max() < 1e-9:
        return 0.0
    nfft = 1 << 20
    sp = np.abs(np.fft.rfft(a * np.hanning(len(a)), nfft))
    fr = np.fft.rfftfreq(nfft, hop)
    sel = (fr > 0.2) & (fr < 60)
    return float(fr[sel][np.argmax(sp[sel])])


def measure(path, meta):
    import numpy as np
    sr, d = load(path)
    name = meta["name"]
    t, e = envelope_db(d, sr)
    t_on = onset(t, e)
    hold = meta["hold_s"]
    noff = meta.get("note_on_s", 0.0) + hold   # nominal key-up
    note = name.rsplit("_", 1)[-1].replace("_8bit", "")
    note = "C4" if "_C4" in name else "A4"
    f0 = F0[note]
    r = {"t_on": t_on}
    pk = e.max()
    r["peak_db"] = float(pk)
    if name.startswith("fm_"):
        ratio = 2.0 if "_r2" in name else 1.0
        if "iatt" in name:
            # index rise: fitted beta every 0.1 s
            bs = []
            for k in range(0, int((hold - 0.1) / 0.1)):
                h = harmonics(d, sr, f0, t_on + k * 0.1, t_on + k * 0.1 + 0.1, int(20000 // f0))
                bs.append(round(float(fit_beta(h, ratio)[0]), 3))
            r["beta_vs_t"] = bs
        else:
            nh = int(20000 // f0)
            h = harmonics(d, sr, f0, t_on + 0.4, t_on + 1.4, nh)
            b, phi, err = fit_beta(h, ratio)
            r.update(beta=float(b), c=float(phi), fit_rms_db=float(err),
                     h_db=[round(float(x), 1) for x in 20 * np.log10(h / h.max() + 1e-12)][:12])
    elif name.startswith("env_"):
        a = 10 ** ((e - pk) / 20)
        def cross(level, after=t_on, falling=False):
            m = t >= after
            idx = np.where(a[m] <= level)[0] if falling else np.where(a[m] >= level)[0]
            return float(t[m][idx[0]]) if len(idx) else None
        if "att" in name:
            r["t10"] = cross(0.1) - t_on
            r["t50"] = cross(0.5) - t_on
            r["t90"] = cross(0.9) - t_on
            r["t100"] = cross(0.99) - t_on
        if "idec" in name:
            tpk = float(t[np.argmax(e)])
            sus = float(np.median(e[(t > noff - 0.3) & (t < noff - 0.05)]) - pk)
            r["sustain_db"] = sus
            ls = 10 ** (sus / 20)
            r["t_half"] = cross(1 - (1 - ls) / 2, tpk, True) - tpk   # halfway (linear) to sustain
            r["t_90pct"] = cross(1 - 0.9 * (1 - ls), tpk, True) - tpk
        if "fdec" in name:
            off = meta.get("note_on_s", 0.0) + hold
            # key-up as seen: the last window before the level starts to drop
            lv = float(np.median(e[(t > off - 0.3) & (t < off - 0.05)]))
            r["hold_db"] = lv - pk
            for dt in (0.1, 0.25, 0.5, 1.0, 2.0):
                m = (t >= off + dt - 0.01) & (t <= off + dt + 0.01)
                if m.any():
                    r[f"db@{dt:g}"] = float(e[m].mean() - lv)
            for dbl in (-6, -20, -40):
                m = (t > off) & (e - lv <= dbl)
                r[f"t{dbl}dB"] = float(t[m][0] - off) if m.any() else None
        if "level" in name or "delay" in name:
            r["steady_db"] = float(np.median(e[(t > t_on + 0.5) & (t < noff - 0.05)]))
        if "delay" in name:
            r["t_start"] = float(t[np.argmax(e > pk - 40)]) - meta.get("note_on_s", 0.0)
    elif name.startswith("chorus"):
        c = float(name.split("_")[0][6:])
        fine = float(name.split("_")[1])
        r["nominal_ratio"] = c + fine
        if abs(c - 1.0) < 1e-9:
            r["beat_hz"] = beat_rate(d, sr, t_on + 0.2, noff - 0.05)
            r["nominal_beat_hz"] = f0 * fine
        else:
            f1 = peak_freq(d, sr, f0, t_on + 0.2, noff - 0.05, 0.03)
            f2 = peak_freq(d, sr, f0 * (c + fine), t_on + 0.2, noff - 0.05, 0.004)
            r["f1"], r["f2"] = f1, f2
            r["ratio"] = f2 / f1
    elif name.startswith("tune"):
        f1 = peak_freq(d, sr, f0, t_on + 0.2, noff - 0.05, 0.05)
        r["f1"] = f1
        r["cents_vs_440"] = 1200 * np.log2(f1 / 440.0)
    return r


def cmd_report(a):
    import glob
    res = {}
    for side, folder in (("sv", a.sv), ("sim", a.sim)):
        for js in sorted(glob.glob(os.path.join(folder, "*.json"))):
            meta = json.load(open(js))
            w = js[:-5] + ".wav"
            if not os.path.exists(w):
                continue
            meta.setdefault("note_on_s", 0.05 if side == "sv" else 0.0)
            try:
                res.setdefault(side, {})[meta["name"]] = measure(w, meta)
            except Exception as e:  # noqa: BLE001
                res.setdefault(side, {})[meta["name"]] = {"error": repr(e)}
    out = json.dumps(res, indent=1, default=float)
    if a.output:
        open(a.output, "w").write(out)
    print(out)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("render")
    r.add_argument("image")
    r.add_argument("out")
    r.add_argument("-j", "--jobs", type=int, default=6)
    r.add_argument("--only", default="fm,env,chorus")
    r.add_argument("--force", action="store_true")
    r.add_argument("--env-clock-ns", dest="env_clock", type=int,
                   help="override the interpolator clock period in ns (experiment)")
    r.set_defaults(fn=cmd_render)
    p = sp.add_parser("report")
    p.add_argument("sv")
    p.add_argument("sim")
    p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
