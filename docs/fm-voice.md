# FM voice specification (M3)

What each register of the original Synclavier II FM synthesizer does, and
how a voice turns them into sound. Registers and channels:
[`devices/d160-fm-interface.md`](devices/d160-fm-interface.md). Code:
`sim/fm.py`, `sim/voice.py`. Status: **pitch decoded and verified**;
envelope, index, shift/pan, volume and wave memory **decoded from NED
source**, with the release path checked against Release L (M3.1a). An
integer voice model renders audio from the register writes (M3.2). Open
items at the end.

## Structure (hardware)

From the card analysis (*Synclavier FM.docx*, see [`sources.md`](sources.md);
a compilation that quotes a forum analysis, so **[secondary]**) and patent
US 4,345,500:

* A card set of 8 voices: **SS1** 8 × 8-bit multiplier + shifter
  (modulation index, ×1/×2/×4/×8 → `ISHC`), **SS2** unsigned sine ROM,
  clock generator ("exactly Fig. 7B in patent 4345500") and 8-bit phase
  register/adder, **SS3** envelope generators (8-bit prescaler, 8-bit rate
  generator, 8-bit up/down counter → `EDIV`, `EADD`, `ELIM`), **SS4**
  interface to the D160 card, wave memory, index and envelope
  interpolators, crystal oscillator, **SS5/SS7** waveform DAC, envelope
  MDAC, volume DAC (and pan on SS7).
* Wave memory: 32 waveforms of 256 points shared by all voices (the two
  extra address bits come from the CPU: `TIM`).
* Each voice = two channels: even = modulator, odd = carrier.

## Pitch (verified)

Per channel, from patent US 4,345,500 and NED's `COMPUTE.OSYN.FREQ`
(identical in Release L ORK-LM, routine at 015322):

```
INC (fn 0) = increment − 1                 8 bits
NNU (fn 1) = 256 − divisor + (INC >> 3)    8 bits
ONU (fn 2) = octave, 0–7

f = K × 2^ONU × increment / divisor,  K = 162.764 Hz
```

* The oscillator adds the increment to an 8-bit accumulator with modulus
  set by the divisor; each carry steps the waveform one point (256 per
  cycle), after a divide by a power of two for the octave. So the step
  rate is 256 × f (≈ 41.67 kHz × 2^ONU × increment / divisor).
* The software side: pitch is a log frequency (1024 steps per octave,
  2816 = A 440). `ONU = (log >> 10) − 1` (at most 7); `(inc, divisor)`
  comes from the **.STAB-6** table indexed by `log & 1023` (1,024 entries
  for keys up to B3, 512-entry tables for the upper octaves, which bring
  the octave down by one or two). Very low frequencies scale inc/divisor
  instead. **[OBS]** `.STAB-6` sectors 0–3 and 4–7 are these tables.
* `K` from `.STAB-6` entry 768 (A 440 at log 2816: ONU 1, inc 123,
  divisor 91): K = 440 / (2 × 123 / 91).

Check against Release L ORK-LM's writes (timbre 0 of `06-TIMBD` bank 0):

| Key | ONU | NNU | INC | f (Hz) | Expected |
|---|---:|---:|---:|---:|---|
| 36 (C3, middle C) | 1 | 159 | 85 | 261.64 | 261.63 |
| 45 (A3) | 1 | 180 | 122 | 440.00 | 440.00 |
| 48 (C4) | 1 | 192 | 126 | 523.32 | 523.25 |
| 49 (C♯4) | 1 | 203 | 113 | 553.88 | 554.37 |
| 57 (A4) | 1 | 238 | 72 | 880.13 | 880.00 |
| 72 (C6) | 2 | 239 | 89 | 2092.68 | 2093.00 |

Errors are the table quantization the patent discusses (≤ 0.15 %).

## Interpolators: envelope and index

Each channel has one interpolator: the **volume envelope** on the odd
(carrier) channel (`EDIV`, `EADD`, `ELIM`), the **index envelope** on the
even (modulator) channel (`IDIV`, `IADD`, `ILIM`). Card analysis (SS3):
"an 8 bit prescaler (divide by n counter) followed by an 8 bit rate
generator (phase accumulator) and 8 bit up/down counter". Encodings from
NED `302-SUB2` (`NEW.SCALE.DIV/ADD`) and `138-PRE1`
(`COMPUTE.INTERP.NUMBERS`):

```
divisor = 256 − DIV   (1–256)     adder = ADD + 1   (1–256)
each clock: prescaler counts; every `divisor` clocks the 8-bit accumulator
adds `adder`; each carry moves the counter one step toward LIM; it stops there.

steps/s = F × (ADD + 1) / (256 × (256 − DIV)),   F ≈ 192 kHz [INFERRED]
```

* The counter output is the 8-bit envelope (to the envelope MDAC) or
  index (to the SS1 multiplier). The limit is a target, up or down: NED
  starts an attack by writing the peak as the limit, a decay by writing the
  sustain level or 0. A new limit is followed at the old rate until the
  rate is rewritten (NED comment in `144-TIM3`).
* **Limit reached → D160 bit 0.** With function 12 selected, NED and
  Release L write the limit (twice, "for hardware accuracy") and read D160:
  bit 0 = 0 when the counter equals the limit. That is how software ends an
  attack (`EPKQ`/`IPKQ` queues) and frees a voice after its final decay.
  With another function selected, bit 0 is the channel-present bit of the
  voice probe. **[INFERRED]** from the software; this is the only reading
  consistent with both uses, because MONITOR writes `ILIM` = 0 to every
  channel before ORK-LM's probe.
* `F`: NED converts a time T (ms) for a full-scale change into adder 256,
  divisor 0.75 T, scaled down by halving both until the divisor fits. Full
  scale is 256 steps for the index (limit = 2 × peak, peak < 128 after the
  shift count is chosen) and 250 for the volume (limit = level / 4, level
  0–1000), giving F = 192 or 187.5 kHz. The model uses 192 kHz; only a
  hardware measurement can settle it.
* Envelope shapes are linear in hardware. NED makes exponential decays in
  software: every 10 ms `EADD` (or `IADD`) = `EDAT` >> 8 with
  `EDAT` ← `EDAT` × TMC / 65536, TMC = 65536 − 819200 / T (T ≥ 150 ms).
  `382-EXP`.

Release L check (`06-TIMBD` bank 0 timbre 0, C4, held 1 s): note-on writes
`EDIV` 377, `EADD` 377, `ELIM` 372 (= 250: peak 1000, attack 0, i.e. one
step per clock, 1.3 ms to the peak). Key-up writes `ELIM` 0 at full rate,
then polls bit 0; 5.6 ms later it reads "reached" and clears the voice
(`IDIV`/`IADD` 377, `ILIM` 0, `ONU` 0, `NNU`/`INC` 377, `VOL` 0), the
clean-up NED `144-TIM3` does "to reduce feed-through". Before the
interpolator was modelled, bit 0 never cleared and ORK-LM instead ran
NED's exponential decay: `EADD` 255, 233, 214, 196, … every 10 ms, which
is exactly TMC for T = 150 ms (`tests/sim/test_fm.py`). So Release L uses
the same scheme as NED.

## Modulation: index, shift count, pan

* The modulator reads the **sine ROM** (SS2, two 74387 PROMs, unsigned
  8-bit). `TIM` is only ever written to odd channels, so the wave memories
  are carrier-only.
* SS1 multiplies the modulator sample by the index counter (8 × 8 bits,
  unsigned) and a shifter picks 8 bits: bits 15–8 for shift 0, down to
  12–5 for shift 3 (×1, ×2, ×4, ×8). The result is added to the carrier's
  8-bit phase (waveform point). At shift 0 the largest offset is
  255 × 255 / 256 = 254 points, just under one carrier period.
* `ISHC` (even, function 13) packs two fields: **bits 7–2 = pan**, bits
  1–0 = shift count (NED: `J = (STEREO & 374) + ISHC`). Pan 0 = all left
  (`600-INIT`); NED's centre is 128. Release L's note-on writes 203 octal
  = centre, shift 3.
* NED chooses the shift count once per partial so the index peak fits in
  7 bits (`COMPUTE.FM.ENV`: halve the peak until < 128, counting the
  halvings); the index limit is then 2 × the scaled peak. The shift count
  is fixed for the note, so large indices have a coarser index envelope
  (as the card analysis noted).

## Wave memory and timbre bits

* 32 memories × 256 points × 8 bits, shared by all voices of a card set
  (SS1: 16 × 1024×4 RAM).
* Load: select a channel, `ZMA` = 0 (zero its memory address register),
  `TIM` = 32 + n (memory n), then `MEM` repeatedly; each write stores a
  byte and increments the address. NED writes each 16-bit table word low
  byte first (`303-SUB3`). Release L loads its memories through channel 15
  (`TIM` 044–047 = memories 4–7, 256 `MEM` writes each).
* Play: `TIM` on the carrier channel selects its memory. NED uses 32 + 0–15
  for timbres and 48 + 8–15 (= memories 24–31) for splicing. Bits 4–0 are
  the memory number; software always sets bit 5 and its function is not
  known.

## Output level

Per carrier: wave sample (waveform MDAC) × envelope counter (envelope MDAC)
× `VOL` (volume DAC, odd function 13) × pan (SS7 pan DAC + a 256 × 8 PROM
pan law, two cards in tandem for left/right). NED `COMPUTE.VOLUME.LEVELS`
maps partial volume 0–1000 to 0–255 for `VOL`. Release L rewrites `VOL`
(here 375 octal = 253) about 345 times a second while a note is held.

## Open

| Item | Needed |
|---|---|
| Interpolator clock F (≈ 192 kHz) | hardware measurement or schematics |
| D160 bit 0 behaviour at power-on and its exact gating | schematics |
| Pan-law PROM contents; whether the envelope MDAC is linear | schematics/ROM dump or recordings |
| `TIM` bit 5; the "INC write also sets ONU = 0, NNU = 255" note in NED `144-TIM3` | schematics or hardware |
| Sine ROM contents (phase offset, 256 × 8 unsigned assumed) | ROM dump |
| Absolute levels and envelope curves | recordings of real hardware (risk R1) |

## Voice model (M3.2)

`sim/voice.py` replays the D162 writes (time, channel, function, value)
through 16 channels and renders stereo audio. State is integer, as in
hardware; only the final mix is floating point.

| Part | Model | Status |
|---|---|---|
| Oscillator | per tick of 256 × 128 × K = 5.3335 MHz: accumulator += increment, modulus divisor; each wrap is a pulse; a 7-stage divider passes one pulse in 2^(7 − ONU) to the 8-bit point counter | step rate **[OBS]** (pitch table); clock tree **[UNKNOWN]**: increment can exceed the divisor (A 440: 123/91), so at this clock one tick can give two pulses |
| Interpolators | `sim.fm.Interpolator`, 192 kHz | **[INFERRED]** |
| Modulator | `SINE_ROM[point]`, round(127.5 + 127.5 sin(2πn/256)) | **[CHOICE]**: ROM not dumped |
| FM | carrier address = (carrier point + (m × index) >> (8 − shift)) & 255 | **[INFERRED]** card analysis |
| Carrier sample | wave memory `TIM` & 31, unsigned, DAC offset binary around 128 | wave data **[OBS]** (NED `COMPUTE.WAVE`: scaled to 0–255 around the DC point; flat = 128); offset **[CHOICE]** |
| Level | (w − 128) × envelope × `VOL`, linear | **[CHOICE]**: MDAC/DAC laws unknown |
| Pan | right = pan / 256, left = 1 − right (`ISHC` bits 7–2) | **[CHOICE]**: pan PROM not dumped |
| Output | sampled at 48 kHz × 4, box filter to 48 kHz | **[CHOICE]**; hardware DACs change at each voice's step rate, analog filtering unknown |

Checks (`tests/sim/test_voice.py`, `test_rtp.py`):

* Oscillator and interpolator closed forms equal clock-by-clock stepping
  (random registers), so an HDL implementation can be compared tick by
  tick.
* A rendered note's fundamental is at `fm.frequency(ONU, NNU, INC)`.
* FM: index 0 gives the pure wave; with modulator = carrier frequency,
  harmonics 2 and 3 appear and grow with the index and shift.
* Release L `06-TIMBD` bank 0 timbre 0: wave memory 4 holds a sine; C4
  renders at 523.3 Hz with harmonics 2 and 3 below 1 %. A C–E–G chord
  (keys 36, 40, 43) renders three equal peaks at 261.6, 329.6, 392.0 Hz.
* `TOMDTA43` timbre 3 in Release L (a later bank, partly misread):
  index envelope (`ILIM` 228), a pitch sweep rewritten every 10 ms and a
  `VOL` decay 150 → 41 over 30 ms; it renders without clipping. Whether
  it sounds like the original needs a recording.

Not modelled: the splice bits of the channel word (QUELITS: bits 8–11
splice memory, 12–15 state), `TIM` bit 5, and the NED note that an `INC`
write also sets `ONU` = 0 and `NNU` = 255.

The HDL voice engine (in `hdl/dev/dev_fm.sv`, up to 32 voices, [`hdl.md`](hdl.md)) computes
the same integer samples (`FMSynth.sample_int`), checked sample for sample.

M3.3 (tuning against recordings of real hardware) needs those recordings
(risk R1, [`bench-checklist.md`](bench-checklist.md)).
