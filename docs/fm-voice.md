# FM voice specification (M3)

What each register of the original Synclavier II FM synthesizer does, and
how a voice turns them into sound. Registers and channels:
[`devices/d160-fm-interface.md`](devices/d160-fm-interface.md). Code:
`sim/fm.py`. Status: **pitch decoded and verified (M3.1a)**; envelope,
index, volume and wave memory still to do.

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

## Still to decode (M3.1a, next)

| Registers | Source to read | Hardware |
|---|---|---|
| `EDIV`, `EADD`, `ELIM` (odd), `VOL` | NED envelope routines (`11-TIMB:137-COMP` "envelope information", `10-INT`); ORK-LM's ~345 `VOL` writes per second | SS3: prescaler, rate generator, up/down counter; SS5/7 envelope and volume DACs |
| `IDIV`, `IADD`, `ILIM`, `ISHC` (even) | same, index envelope | SS4 index interpolator; SS1 multiplier + shifter |
| `TIM`, `ZMA`, `MEM` | wave memory loading (1,032 writes per recall: 4 × 256 + 8) | SS1/SS4 wave memory, 32 × 256 points |

Absolute calibration of sound (levels, envelope curves) needs recordings
of real hardware (risk R1).
