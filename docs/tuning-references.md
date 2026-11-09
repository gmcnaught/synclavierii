# Tuning references for M3.3 (software emulators)

M3.3 tunes the voice model (`sim/voice.py`, `hdl/dev/dev_fm.sv`)
against reference audio. Recordings of a real Synclavier II are still the
final acceptance (risk R1). Until they exist, two emulators by the
original programmer can serve as secondary references.

## Candidates

| | Synclavier³ "Virtual" (Synclavier Digital) | Synclavier V (Arturia) |
|---|---|---|
| What it runs | "a real time emulation environment to actually execute the original Synclavier compiled code"; the installer's Virtual option "operates Synclavier³ without any hardware attached" | "Original programmer + original code = the original Synclavier synthesis engine", co-created with Cameron Jones |
| Differences from Release L / Model B | A later Real-Time Program (Model D era); its voice output is a software model of the voice cards | 12 partials instead of 4; variable bit depth instead of 8-bit; new UI |
| Same timbres as ours | Yes: the `Original-NED-Sample-Patch-Libraries` banks are a Synclavier³-era export (`timbre-libraries.md`), so the FM-only timbres `TOMDTA43` 12–18 load directly | By hand: enter the physical parameters from the `NN-Entry.txt` files |
| Cost | Stand-alone licence; no demo listed | Free demo (terms not stated on the product page) |

Both are emulations, so a match shows agreement with NED's own model of
the hardware, not with the hardware. Where they disagree with each other,
neither settles the question.

## What a recording can settle

| Model choice (`fm-voice.md`) | Measured from | Test |
|---|---|---|
| Oscillator clock (656015360/123 Hz) and divisor scheme | pitch of a pure carrier | A4, C4, C2, C6 held 2 s; fundamental by FFT; error in cents |
| Interpolator rates (envelope time units) | volume envelope | known attack/decay/release times; 10–90 % times from the RMS envelope |
| Modulation index scaling (`>> (8 − shift)`) | sideband levels | FM ratio 1:1, index 0 → max in steps; sideband ratios vs Bessel functions |
| Sine ROM | harmonic content of an index-0 carrier | THD of a pure tone |
| DAC and pan law | level and stereo balance | one voice at pan left / centre / right; full-scale level |

## Capture protocol

* 48 kHz (or 44.1 kHz), 24-bit WAV, stereo, no effects (reverb, chorus,
  EQ off), master volume at a noted fixed setting.
* One note per file, held 2 s, then 2 s of release; file name = timbre,
  note, setting (e.g. `TOMDTA43-12_A4.wav`).
* Synclavier³: load bank `TOMDTA43`, timbres 12–18; notes C2, C4, A4, C6.
* Synclavier V: patches typed in from `TOMDTA43/12-Entry.txt` … `18-Entry.txt`
  (carrier coefficients, FM ratio, volume and index envelopes), bit depth
  8 if offered; the same notes.
* Plus three synthetic patches in both, if the UI allows: a pure sine
  (one carrier coefficient, no FM); FM 1:1 with a fixed index at three
  index settings; a slow attack (1 s) and decay (1 s) on a pure sine.

The simulator renders the same timbres through Release L
(`sim.rtp --bank-file`, `--wav`), so each pair can be compared in
pitch, envelope timing and spectrum.
