#!/usr/bin/env python3
"""Capture reference notes from Arturia Synclavier V (M3.3 tuning).

Needs a Python 3.12 venv with pedalboard + numpy (no pedalboard wheel for
newer Pythons). Procedure (docs/tuning-references.md):

1. The script opens the plugin editor (it loads "Naked Planet"; MIDI is
   ignored while the editor is closed).
2. The user selects the factory preset "Simple Sine (Clean)", opens the
   ENGINE tab and checks that the modulator has harmonic 1 only, then
   creates the go-file (path printed at start).
3. The script bypasses effects, checks that the patch is a pure sine,
   renders every test in real time (512-sample blocks) and writes one WAV
   + one JSON (parameter display values) per test to OUT.

    sv-venv/bin/python tools/sv_capture.py OUT [--only fm,env,chorus]
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import wave

import numpy as np
import pedalboard

PLUGIN = "/Library/Audio/Plug-Ins/VST3/Synclavier V.vst3"
SR = 48000
BLOCK = 512
A4, C4 = 69, 60


def write_wav(path, audio):
    """audio: (2, n) float32 → 24-bit stereo WAV."""
    a = np.clip(audio.T, -1.0, 1.0 - 2 ** -23)
    i = np.ascontiguousarray((a * 2 ** 23).astype("<i4"))
    b = i.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(b)


def _num(s):
    s = s.strip()
    if s in ("Off",):
        return -1e9
    m = re.match(r"[-+]?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


class SV:
    def __init__(self):
        self.p = pedalboard.load_plugin(PLUGIN)
        self.p.process([], duration=0.1, sample_rate=SR, num_channels=2, reset=True)

    def raw(self, name, value):
        self.p.parameters[name].raw_value = value

    #: Linear parameters set exactly (display rounding hides small errors):
    #: ratios/chorus 0-16 (raw = v / 16), fine -0.1..+0.1 (raw = 0.5 + v / 0.2).
    LINEAR = {"partial_fm_ratio_1": (0.0, 16.0), "partial_chorus_1": (0.0, 16.0),
              "timbre_chorus": (0.0, 16.0), "partial_fm_ratio_fine_1": (-0.1, 0.1),
              "partial_chorus_fine_1": (-0.1, 0.1), "timbre_chorus_fine": (-0.1, 0.1)}

    def disp(self, name, target):
        """Set a monotonic numeric parameter to a display value (bisection)."""
        pr = self.p.parameters[name]
        if name in self.LINEAR:
            lo, hi = self.LINEAR[name]
            pr.raw_value = (target - lo) / (hi - lo)
            return
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            pr.raw_value = mid
            v = _num(pr.string_value)
            if v < target:
                lo = mid
            else:
                hi = mid
        best = min((lo, hi), key=lambda r: (setattr(pr, "raw_value", r),
                                            abs(_num(pr.string_value) - target))[1])
        pr.raw_value = best
        got = _num(pr.string_value)
        if abs(got - target) > max(0.02 * abs(target), 0.006):
            raise ValueError(f"{name}: wanted {target}, got {pr.string_value}")

    def snapshot(self):
        return {k: self.p.parameters[k].raw_value for k in self.p.parameters}

    def strings(self, prefixes):
        return {k: self.p.parameters[k].string_value for k in self.p.parameters
                if k.startswith(prefixes)}

    def render(self, events, seconds):
        """events: [(seconds, midi bytes)]; real-time paced 512-sample blocks."""
        n = int(seconds * SR)
        out, pos, t0 = [], 0, time.time()
        while pos < n:
            blk = [(m, (t * SR - pos) / SR) for t, m in events if pos <= t * SR < pos + BLOCK]
            out.append(self.p.process(blk, duration=BLOCK / SR, sample_rate=SR,
                                      num_channels=2, reset=False))
            pos += BLOCK
            dt = t0 + pos / SR - time.time()
            if dt > 0:
                time.sleep(dt)
        return np.concatenate(out, axis=1)[:, :n]

    def note(self, key, hold, tail, vel=100):
        ev = [(0.05, bytes([0x90, key, vel])), (0.05 + hold, bytes([0x80, key, 0]))]
        return self.render(ev, 0.05 + hold + tail)


def harmonics_db(x, f0, nh=5):
    seg = x[int(0.3 * SR):int(1.3 * SR)]
    w = np.hanning(len(seg))
    sp = np.abs(np.fft.rfft(seg * w))
    df = SR / len(seg)
    lv = [sp[max(0, int(round(h * f0 / df)) - 15):int(round(h * f0 / df)) + 16].max()
          for h in range(1, nh + 1)]
    return [20 * np.log10(v / lv[0] + 1e-20) for v in lv]


# ---- test definitions: (name, {param: display value or ("raw", r)}, key, hold, tail)
BASE = {
    "timbre_bit_depth": ("raw", 0.0),           # Default
    "timbre_modulation": 0.0,
    "partial_modulation_1": 0.0,
    "partial_fm_ratio_1": 1.0,
    "partial_fm_ratio_fine_1": 0.0,
    "partial_chorus_1": 1.0,                    # 1.0 = preset default; 0.0 adds a ~0 Hz chorus voice
    "timbre_chorus": 1.0,
    "timbre_chorus_fine": 0.0,
    "partial_chorus_fine_1": 0.0,
    "partial_tuning_1": 0.0,
    "partial_pan_1": ("raw", 0.0),              # hard left: one channel, no pan law
    "partial_volume_1": 0.0,                    # 0 dB
    "timbre_volume": 0.0,
    "partial_decay_shape_1": ("raw", 1.0),      # Match Synclavier II
    "volume_envelope_delay_1_s": 0.0,
    "volume_envelope_attack_1_s": 0.0,
    "volume_envelope_initial_decay_1_s": 0.0,
    "volume_envelope_final_decay_1_s": 0.0,
    "volume_envelope_peak_1": 100.0,
    "volume_envelope_sustain_1": 100.0,
    "index_envelope_delay_1_s": 0.0,
    "index_envelope_attack_1_s": 0.0,
    "index_envelope_initial_decay_1_s": 0.0,
    "index_envelope_final_decay_1_s": 0.0,
    "index_envelope_peak_1": 100.0,
    "index_envelope_sustain_1": 100.0,
}


def tests(only):
    t = []
    if "fm" in only:
        # Item 1: F.M. Amount sweep, constant index envelope 100, ratio 1 and 2.
        for ratio in (1.0, 2.0):
            for amt in (0.01, 0.02, 0.03, 0.05, 0.07, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0):
                if ratio == 2.0 and amt not in (0.02, 0.05, 0.1, 0.2):
                    continue
                t.append((f"fm_r{ratio:g}_amt{amt:g}_A4",
                          {"timbre_modulation": 1.0, "partial_modulation_1": amt,
                           "partial_fm_ratio_1": ratio}, A4, 1.5, 0.3))
        # Index envelope level → index (Amount fixed 0.1).
        for lvl in (6.25, 17.0, 43.8):
            t.append((f"fm_r1_amt0.1_ienv{lvl:g}_A4",
                      {"timbre_modulation": 1.0, "partial_modulation_1": 0.1,
                       "index_envelope_peak_1": lvl, "index_envelope_sustain_1": lvl},
                      A4, 1.5, 0.3))
        # F.M. Modulation (timbre) vs F.M. Amount (partial).
        t.append(("fm_r1_amt1_tmod0.1_A4",
                  {"timbre_modulation": 0.1, "partial_modulation_1": 1.0}, A4, 1.5, 0.3))
        # Index envelope timing: 1 s attack 0 → 100, Amount 0.1.
        t.append(("fm_r1_amt0.1_iatt1s_A4",
                  {"timbre_modulation": 1.0, "partial_modulation_1": 0.1,
                   "index_envelope_attack_1_s": 1.0}, A4, 2.0, 0.3))
        # 8-bit with FM.
        t.append(("fm_r1_amt0.1_A4_8bit",
                  {"timbre_modulation": 1.0, "partial_modulation_1": 0.1,
                   "timbre_bit_depth": ("raw", 0.25)}, A4, 1.5, 0.3))
    if "env" in only:
        # Items 2 and 3: volume envelope times and levels.
        for a in (0.1, 0.5, 1.0, 2.0):
            t.append((f"env_att{a:g}s_A4", {"volume_envelope_attack_1_s": a}, A4, a + 1.0, 0.3))
        t.append(("env_delay0.5s_att0.5s_A4", {"volume_envelope_delay_1_s": 0.5,
                                               "volume_envelope_attack_1_s": 0.5}, A4, 1.8, 0.3))
        for d in (0.25, 1.0):
            for s in (50.0, 25.0):
                t.append((f"env_idec{d:g}s_sus{s:g}_A4",
                          {"volume_envelope_initial_decay_1_s": d,
                           "volume_envelope_sustain_1": s}, A4, d * 3 + 0.5, 0.3))
        for f in (0.25, 1.0, 2.0):
            # "True Exponential" (raw 0) renders NaN samples in v2.7 demo.
            for shape, raw in (("match", 1.0),):
                t.append((f"env_fdec{f:g}s_{shape}_A4",
                          {"volume_envelope_final_decay_1_s": f,
                           "partial_decay_shape_1": ("raw", raw)}, A4, 0.8, f * 3 + 0.5))
        t.append(("env_fdec1s_match_C4", {"volume_envelope_final_decay_1_s": 1.0}, C4, 0.8, 3.5))
        for lvl in (100.0, 50.0, 25.0, 10.0, 2.5):
            t.append((f"env_level{lvl:g}_A4", {"volume_envelope_peak_1": lvl,
                                               "volume_envelope_sustain_1": lvl}, A4, 1.5, 0.3))
        for vol in (-6.0, -20.0):
            t.append((f"env_pvol{vol:g}dB_A4", {"partial_volume_1": vol}, A4, 1.5, 0.3))
    if "chorus" in only:
        # Item 5: detune and chorus beat rates.
        for c, f in ((1.0, 0.002), (1.0, 0.01), (1.0, 0.05), (2.0, 0.005), (0.5, 0.004)):
            for key, kn in ((A4, "A4"), (C4, "C4")):
                t.append((f"chorus{c:g}_{f:+g}_{kn}",
                          {"partial_chorus_1": c, "partial_chorus_fine_1": f}, key, 3.0, 0.3))
        for cents in (-10.0, 10.0):
            t.append((f"tune{cents:+g}c_A4", {"partial_tuning_1": cents}, A4, 1.5, 0.3))
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--only", default="fm,env,chorus")
    ap.add_argument("--go-file", default=None)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    go = args.go_file or os.path.join(args.out, "GO")
    if os.path.exists(go):
        os.remove(go)
    only = set(args.only.split(","))
    sv = SV()
    done = threading.Event()
    log = open(os.path.join(args.out, "capture.log"), "a")

    def say(*a):
        msg = " ".join(str(x) for x in a)
        print(msg, flush=True)
        log.write(time.strftime("%H:%M:%S ") + msg + "\n")
        log.flush()

    def apply(params):
        for k, v in {**BASE, **params}.items():
            if isinstance(v, tuple):
                sv.raw(k, v[1])
            else:
                sv.disp(k, v)
        for i in (1, 2, 3):
            sv.raw(f"effect{i}_selector", 0.0)

    def worker():
        try:
            time.sleep(6)
            first = sv.snapshot()
            say(f"WAITING: select 'Simple Sine (Clean)', check ENGINE modulator = harmonic 1 only, then: touch {go}")
            while not os.path.exists(go):
                time.sleep(0.5)
            changed = sum(1 for k, v in sv.snapshot().items() if first[k] != v)
            say(f"go; {changed} parameters differ from the start-up preset")
            apply({})
            sv.note(A4, 0.3, 0.3)  # throw-away note after parameter changes
            x = sv.note(A4, 1.5, 0.3)[0]
            h = harmonics_db(x, 440.0)
            say("pure-sine check H1..H5 dB:", [round(v, 1) for v in h])
            if max(h[1:]) > -50:
                say("ABORT: patch is not a pure sine (wrong preset or carrier harmonics)")
                return
            seg = x[int(0.3 * SR):int(1.4 * SR)]
            rms = [np.sqrt(np.mean(seg[i:i + 4800] ** 2)) for i in range(0, len(seg) - 4800, 2400)]
            wob = 20 * np.log10(max(rms) / min(rms))
            say(f"level flatness while held: {wob:.2f} dB")
            if wob > 0.5:
                say("ABORT: level varies while held (chorus, tremolo or vibrato still on)")
                return
            todo = tests(only)
            say(f"{len(todo)} tests, about {sum(0.6 + h + tl for _, _, _, h, tl in todo) / 60:.1f} min")
            for i, (name, params, key, hold, tail) in enumerate(todo):
                try:
                    apply(params)
                    sv.note(key, 0.2, 0.3)
                    audio = sv.note(key, hold, tail)
                    np.save(os.path.join(args.out, name + ".npy"), audio)
                    write_wav(os.path.join(args.out, name + ".wav"), audio)
                except Exception as e:  # noqa: BLE001
                    say(f"[{i + 1}/{len(todo)}] {name} FAILED {e!r}")
                    continue
                meta = {"name": name, "key": key, "hold_s": hold, "tail_s": tail,
                        "note_on_s": 0.05, "set": {k: (v if not isinstance(v, tuple) else v[1])
                                                   for k, v in {**BASE, **params}.items()},
                        "display": sv.strings(("partial_", "timbre_", "volume_envelope_", "index_envelope_", "decay_", "effect1_selector", "effect2_selector", "effect3_selector"))}
                meta["display"] = {k: v for k, v in meta["display"].items()
                                   if not re.search(r"_([2-9]|1[0-2])(_s)?$", k)}
                json.dump(meta, open(os.path.join(args.out, name + ".json"), "w"), indent=1)
                say(f"[{i + 1}/{len(todo)}] {name} peak {np.abs(audio).max():.3f}")
            say("DONE")
        except Exception as e:  # noqa: BLE001
            say("ERROR", repr(e))
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    sv.p.show_editor(done)


if __name__ == "__main__":
    sys.exit(main())
