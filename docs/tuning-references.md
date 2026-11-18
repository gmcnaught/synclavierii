# Tuning references for M3.3 (software emulators)

M3.3 tunes the voice model (`sim/voice.py`, `hdl/dev/dev_fm.sv`)
against reference audio. Recordings of a real Synclavier II are still the
final acceptance (risk R1). Until they exist, Arturia's Synclavier V is
the only usable software reference.

## Candidates

| | Synclavier V (Arturia) | Synclavier³ "Virtual" (Synclavier Digital) |
|---|---|---|
| What it runs | "Original programmer + original code = the original Synclavier synthesis engine", co-created with Cameron Jones | The original compiled code, against real voice cards |
| Audio | Yes (VST3/AU/standalone) | **None.** Synclavier³ assumes real hardware; with no cards the Virtual install only sends MIDI out (user, 2026-11-17). Not a reference. |
| Differences from Release L / Model B | 12 partials instead of 4; bit depth 4–24 (default not 8); 44.1/48 kHz output; pitch exactly 12-TET | — |
| Same timbres as ours | By hand: enter the physical parameters from the `NN-Entry.txt` files | — |
| Cost | $149; demo: no preset save/load/import/export, 20 min per launch | Stand-alone licence |

Other software considered and rejected (2026-11-17): Synclavier Go! (iOS,
same engine lineage as Synclavier V), Regen (hardware), Syncla-X
(abandoned 2018, downloads removed, no stated hardware reference), and the
synclavier.com Webclavier (obfuscated JavaScript synthesis, 8 fixed
timbres with unknown parameters).

Synclavier V is an emulation by the same lineage, so a match shows
agreement with that model of the hardware, not with the hardware.

## What Synclavier V can and cannot settle

| Model choice (`fm-voice.md`) | Synclavier V usable? | Test |
|---|---|---|
| Oscillator clock (656015360/123 Hz) and divisor scheme | **No**: its pitch is 12-TET within 0.04 c (C4, A4, C6), so it does not model divisor quantization | needs hardware recordings |
| Interpolator rates (envelope time units) | Yes | known attack/decay/release times; 10–90 % times from the RMS envelope |
| Modulation index scaling (`>> (8 − shift)`) | Yes, with a sine-modulator patch | FM ratio 1:1, index 0 → max in steps; sideband ratios vs Bessel functions |
| Sine ROM / 8-bit quantization | Yes, at Bit Depth 8 | harmonic content of an index-0 carrier |
| DAC and pan law | Partly (its DAC-error model is its own) | one voice at pan left / centre / right |

Pitch acceptance against Synclavier V: ±3 c per note. The core uses NED's
`.STAB-6` increment/divisor table (worst case 0.15 % ≈ 2.6 c, e.g. C♯4
−1.5 c); Synclavier V is exact 12-TET. Not perceptible on single notes.
Exception: timbres with partials detuned against each other (chorus,
beating) — the table rounding is the same order as the intended detune,
so beat rates may differ audibly from Synclavier V. Compare those by
beat rate, not pitch, and do not treat a mismatch as a core defect.

First capture (2026-11-17, preset "simple sine (clean)", effects
bypassed, 48 kHz): at Default bit depth H2–H5 are below −116 dB; at
8 Bits the distortion is odd-order only, H3 ≈ −57.5 dB and H5 ≈ −62 dB
relative to the fundamental, the same at C2, C4, A4 and C6.

### Sim comparison: pure sine (2026-11-17)

`sim.voice.FMSynth` driven by a synthetic D162 log (one full-scale sine in
wave memory, index 0, envelope 255, VOL 255, pan centre), 48 kHz, same FFT
analysis (Hann, 1 s at 0.3–1.3 s, ±15-bin harmonic exclusion):

| dB re fundamental | H2 | H3 | H4 | H5 | worst non-harmonic, 20 Hz–20 kHz |
|---|---|---|---|---|---|
| Synclavier V, 8 Bits | −86 | −57.5 | −86 | −62 | −75 to −79 (noise floor) |
| sim, wave `round(127.5+127.5 sin)`, oversample 4 (before M23) | −84 | −62.5 | −84 | −68 | **−57.5 (C4 @ 9.2 kHz), −61 (A4 @ 17 kHz)** |
| sim, same, 768 kHz + FIR (M23), 110 Hz–4.2 kHz | −84 | −62.5 | −84 | −68 | −71 … −77 |
| sim, wave `round(128+127 sin)` | −101 … −131 | −68.5 | −100 … −131 | −66 | same as above |

* Harmonic distortion: both are odd-order 8-bit quantization; Synclavier V
  is ~5 dB stronger at H3. The sine-ROM and wave-memory scaling are
  [CHOICE] (`fm-voice.md`), so this does not show either is right.
* Non-harmonic spurs (before M23): the sim and the HDL point-sampled the
  voice's staircase (steps at 256 × f, e.g. 67 kHz for C4) at 192 kHz and
  averaged 4:1, so staircase images aliased into the audio band at −48 to
  −69 dB depending on the note (worst: 1568 Hz, −48 dB at 15.8 kHz). The
  staircase itself, low-pass filtered without sampling, is at −66 to
  −79 dB. **Fixed in M23**: 768 kHz instants and a 512-tap FIR
  (`sim/pcm.py`, `hdl/dev/pcm_out.sv`) give −71 to −77 dB at 8 notes from
  110 Hz to 4.2 kHz
  (`tests/sim/test_pcm.py`).
* What remains near −66 to −73 dB at high notes is in the model's
  staircase: its steps fall on the 5.3333 MHz oscillator tick grid
  (`OSC_CLOCK` = 32 MHz / 6 since #83; divider chain [UNKNOWN] in `fm-voice.md`); the same
  staircase on a 4× finer grid is cleaner (2637 Hz: −66 → −73 dB;
  1568 Hz: −71 → −89 dB). The real cards' clock would settle it.
* Not comparable: Synclavier V "C6" is 1046.5 Hz; the doc's ORK-LM key 72
  is 2093 Hz. Harmonic levels did not depend on pitch in either.

### Envelopes and FM (2026-11-17)

* Attack 1.000 s (simple sine (clean), A4): amplitude rises linearly
  (0.10 / 0.25 / 0.50 / 0.75 / 1.00 of peak at 0.1 / 0.25 / 0.5 / 0.75 / 1.0 s).
  The sim's NED attack for 1000 ms (`ned_interp_numbers`, volume full
  scale 250) is linear, 974 ms: 2.6 % shorter.
* Final decay 1.000 s, decay shape "Match Synclavier® II": −3.1 dB at
  0.5 s, −7.4 dB at 1.0 s, 10 % at 1.9 s, 1 % at 2.5 s after note-off.
  Not yet compared: the sim's release runs through NED's exponential TMC
  steps in the RTP, so it needs an RTP render of a timbre with a 1 s
  final decay.
* FM, ratio 1.0, F.M. Amount 1.000, F.M. Modulation 1.000, modulator
  harmonic 1 only, index envelope 10…100: the index is already very large
  at 10 (H3, H5, H7 above H1) and the spectra do not fit a single
  sine-modulator PM; the knob-to-index mapping is unknown. Next: a sweep at
  F.M. Amount 0.02–0.3.
* Captures need, besides the preset, `partial_modulation_N` (F.M.
  Amount) and `timbre_modulation` (F.M. Modulation) > 0 for any FM; both
  are host parameters. The modulator harmonics are on the ENGINE tab of
  the screen view (the manual's TIME SLICES).

### Output level and pan law (2026-11-17)

A4 sine, one partial/voice at full level; Synclavier V "simple sine
(clean)" with effects bypassed; the core through `sim/voice.py` + `sim/pcm.py`
(VOL 255, envelope 255; NED's peak of 250 is −0.15 dB less):

| | Synclavier V (timbre volume 0 dB) | core | V − core |
|---|---|---|---|
| hard left, peak | 0.501 (−6.0 dBFS) | 0.248 (−12.1 dBFS) | +6.1 dB |
| centre, peak per channel | 0.354 (−9.0 dBFS) | 0.124 (−18.1 dBFS) | +9.1 dB |

* Timbre volume is true dB (0 / −6 / −12 / −20 → 0 / −6.0 / −12.0 / −20.0
  dB); the preset's default is −10 dB. Velocity 127 / 100 / 64: no effect
  in this preset.
* Pan law: Synclavier V is equal-power (centre = 1/√2 of hard left);
  the core was linear (centre = 1/2), a [CHOICE] because the 256 × 8
  pan-law PROM is not dumped (`fm-voice.md`). A PROM suggests a non-linear
  law; Synclavier V's equal-power law agrees [INFERRED]. **The core is
  equal-power since M23** (`tools/gen_pan_law.py`).
* Level: the table above is the core at gain 1/4. Since M23 the core's gain
  is 1/16 (32 voices clipped at 1/4), so one full voice hard-panned is
  −24.1 dBFS peak and Synclavier V is 18.1 dB louder; centred, with equal
  power, −27.1 dBFS, also 18.1 dB below Synclavier V. For A/B listening,
  +18 dB on the core recording (or −18 dB on Synclavier V). Synclavier V's
  absolute level is Arturia's choice, not the instrument's.

## M24: FM index, envelopes and chorus against the sim (2026-11-17)

`tools/sv_capture.py` (53 notes, Synclavier V licensed copy, preset
"Simple Sine (Clean)", effects bypassed, partial and timbre chorus 1.0 =
off, held level flat to 0.00 dB) against `tools/sv_compare.py render`:
the same settings as one-partial `NN-Entry.txt` timbres through
`tools/stmb.py`, bank 0 of `06-TIMBD`, Release L ORK-LM in the simulator
(key 45 = A 440, key 36 = C 261.6). Results: `out/sv-compare.json`
(192 kHz) and `out/sv-compare-333k.json`.

**FM index.** Synclavier V: β = 1.533 × F.M. Amount × F.M. Modulation ×
index level (0–100), from phase-modulation fits within 0.4 dB at Amount
0.02–0.2, index 6.25–100, ratios 1 and 2 (14 captures; Amount 0.01 gives
1.23, β > 40 cannot be fitted below 20 kHz). The factory presets mostly use
Amount 0.4 × Modulation 0.4; there β = 0.02453 rad per NED index unit
(text `IEnvPeak` 0–1000 = Synclavier V level × 10). The core's model,
2π × 255 / 65536 = 0.02445 per unit, is 0.3 % lower; the sim reproduces
its model within 0.5–3.5 % (integer truncation at small indices). The
index attack rises linearly in both.

**Interpolator clock (M24).** At 192 kHz the sim's volume attacks were
1.72–1.81× Synclavier V's and the initial decays 1.5–3×. The timbre stores
attack times in 0.5625 ms units, so the clock is 333 1/3 kHz, the rate
NED itself states ("333333 * INCR - MATCHES CLOCK RATE OF SYNTH",
`144-TIM1`; `fm-voice.md`); at that clock:

| | Synclavier V | sim, 333 1/3 kHz | sim, 192 kHz |
|---|---|---|---|
| attack 0.1 / 0.5 / 1 / 2 s, time to 99 % | 0.098 / 0.495 / 0.990 / 1.965 s | 0.105 / 0.488 / 0.980 / 1.958 | 0.177 / 0.858 / 1.698 / 3.375 |
| attack 1 s, time to 50 % | 0.490 | 0.492 | 0.860 |
| index attack 1 s (β at 2.4 rad, P 100) reaches peak | 1.0 s | 1.0 s | 1.8 s |
| initial decay 0.25 s → sustain 50: halfway / 90 % | 0.037 / 0.065 s | 0.033 / 0.070 | 0.057 / 0.145 |
| initial decay 1 s → sustain 50: halfway / 90 % | 0.105 / 0.242 s | 0.120 / 0.282 | 0.220 / 0.583 |
| initial decay 1 s → sustain 25: halfway / 90 % | 0.180 / 0.417 s | 0.220 / 0.495 | 0.420 / 1.282 |
| final decay 1 s ("Match Synclavier® II"): −6 / −20 / −40 dB | 0.28 / 0.68 / 0.88 s | 0.41 / 0.87 / 1.02 | 0.77 / — / — |
| final decay 0.25 s: −6 / −20 / −40 dB | 0.07 / 0.17 / 0.21 s | 0.16 / 0.27 / 0.30 | 0.25 / — / — |

* Attacks match within 12 ms; initial decays within 0–20 %.
* Final decays: the sim's starts about 0.1 s later (−0.4 dB vs −2.0 dB
  at 0.1 s after key-up) and is shallower at first; the end (−40 dB) is
  0.09–0.14 s later. Not explained: Release L's key-up path (key scan,
  10 ms exponential steps) against Synclavier V's own decay model.
  The 2 s final-decay capture overlaps the throw-away note's tail and is
  left out.
* Delay 0.5 s: note starts at 0.506 s (Synclavier V) and 0.521 s (sim).

**Levels.** Envelope levels 100 / 50 / 25 / 10 / 2.5: −6.02 / −12.04 /
−20.0 / −32.0 dB in Synclavier V and −6.02 / −12.11 / −19.98 / −32.37 dB
in the sim (linear amplitude). Partial volume is true dB in Synclavier V.

**Chorus and tuning.** Beat rates with chorus 1.002 / 1.01 / 1.05 at A4
and C4 agree within 0.02 Hz (0.903 vs 0.907 Hz, …, 22.039 vs 22.040 Hz).
Chorus 2.005 plays at 2.0053 (Synclavier V) and 2.0041 (sim, −1 c), 0.504
at 0.5041 in both. Partial tuning +10 c: +10.6 c vs +8.1 c; −10 c: −10.8 c
in both. The differences are the `.STAB-6` table rounding (±2.6 c).

**Synclavier V notes.** Chorus 1.0 is "off": 0.0 adds a chorus voice at a
ratio near 0, which beats at ~0.9 Hz (the first M24 capture had it and was
discarded). Ratio and chorus parameters are linear, raw = value / 16 (the
display's rounding hides errors). Decay shape "True Exponential" renders
NaN samples (v2.7). The earlier envelope and FM notes above were taken
without these settings checked; the M24 values supersede them.

## Headless capture with pedalboard

Spotify `pedalboard` (Python 3.12 venv; no wheel for 3.15) loads
`/Library/Audio/Plug-Ins/VST3/Synclavier V.vst3`. Findings:

* 924 host parameters (859 in the AU): FM ratio/fine, volume and index
  envelopes, partial volume/pan/tuning, `timbre_bit_depth` (raw 0.25 =
  8 Bits), `effectN_selector` (raw 0.0 = Bypass). **Not exposed:** the 24
  carrier and modulator harmonic levels and the modulator waveform.
* Without the editor window open, the plugin **ignores MIDI** (a no-MIDI
  render equals a note render to 3e-7; same in the AU). Parameters set
  headlessly start at raw 0 (no preset).
* Opening the editor loads the default preset (Naked Planet), overwriting
  parameters set before it opened.
* Working procedure: prime with `reset=True` on the main thread; start a
  worker thread; call `show_editor(close_event)`; the user selects the
  preset; the worker waits until the parameters match a saved snapshot of
  that preset, bypasses the effects, sets the test parameters, then renders
  notes in 512-sample blocks with `reset=False`, paced in real time, and
  sets the close event. The first note after a change can be dropped;
  render a throw-away note first.
* `tools/sv_capture.py OUT` does all of this; the user selects the preset,
  checks the ENGINE tab (modulator harmonic 1 only) and creates `OUT/GO`.
  It aborts unless the patch is a pure sine with a flat held level.
  `tools/sv_compare.py render IMAGE OUT` renders the matching sim notes
  (under `pypy3` when present: same output, ~6× faster) and
  `tools/sv_compare.py report SV SIM` measures both.

## Capture protocol

* 48 kHz, 24-bit WAV, stereo, effects bypassed, timbre volume noted.
* One note per file, held 1.5–2 s, then release; file name = patch,
  note, bit depth (e.g. `sine_A4_8bit.wav`).
* Patches: a pure sine (one carrier harmonic, no modulator); FM 1:1 with a
  sine modulator at three index settings; a slow attack (1 s) and decay
  (1 s) on a pure sine; TOMDTA43 12–18 typed in from the `NN-Entry.txt`
  files. Notes C2, C4, A4, C6; bit depth Default and 8.

The simulator renders the same timbres through Release L
(`sim.rtp --bank-file`, `--wav`), so each pair can be compared in
envelope timing and spectrum.
