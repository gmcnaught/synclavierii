# Poly output: F0-rate mix and anti-aliasing (M26)

Code: `sim/devices/poly.py` (P(m)), `sim/pcm.py` (`PolyBox`, `x_in`,
`Limiter`), `hdl/dev/dev_poly.sv`, `hdl/dev/poly_box.sv`,
`hdl/dev/pcm_out.sv`, `hdl/dev/pcm_limit.sv`, `hdl/board/ddram_word.sv`.
Output levels and the limiter: §7. Output reverb (`hdl/dev/pcm_reverb.sv`): §9.

## 1. Problem (before M26)

On each 48 kHz instant every sounding voice's word `mem[base + pos]` was read
and mixed, and the 16-bit result was added to the FM PCM *after*
`pcm_out`'s filter. A voice steps on the F0 grid (9900 ns, 101 010.1 Hz) and
each word stays on its DAC until the next step (docs/poly-synth.md 3.2,
3.8). Point-sampling that staircase at 48 kHz folds its content above 24 kHz
and its images at k·F0 ± f into the audio band, unfiltered.

Measured (`tests/sim/test_pcm.py` `test_poly_aliasing`): a voice stepping at
F0 playing a 17 kHz sine has an image at F0 − 17 kHz = 84.0 kHz, which
folds to 12.0 kHz. Point-sampled at 48 kHz it is 13.9 dB below the tone; through
the M26 path it is 124 dB below. The tone level changes by 0.1 dB.

## 2. Model (sim and HDL, bit for bit)

At rate tick m (time m·9900 ns), in this order:

1. **Mix.** `P(m) = Σ_v route((dac_v × EVAL_v × {L,R}cur_v + 2^19) >> 20)`
   (4 bits below the DAC word's LSB, rounded; §8), the gains
   as they are at the tick, routed by the distributor's output pair (mono
   cards: the right sum on both sides). No clip. P(m) is the poly output
   for [m·9900, (m+1)·9900).
2. **Latch.** Every DAC takes the word at its voice's address (base +
   position; a stereo slave: its master's + 1) as memory holds it now; 0
   when the voice (a slave: its master) is off or the address is outside
   the bin.
3. **Step** (unchanged).

Every word a voice steps to is heard for one step period, 1-2 ticks
(9.9-19.8 µs) after the step [CHOICE: the HDL fetches the word in the tick
between latch and mix]. A rate tick and an envelope tick at the same time:
the rate tick first. A CPU write lands between ticks, as before.

**To 768 kHz (`PolyBox`, `poly_box.sv`).** FM instant k at t_k
(`floor(k·1e9/768000)` from reset), interval [t_prev, t_k), d = t_k − t_prev:

```
boundary b = m·9900 < t_k (the next unused):  y = P_cur·(b − t_prev) + P(m)·(t_k − b); P_cur = P(m)
else:                                         y = P_cur·d
x_poly = y·RECIP[d] >> ps     RECIP[1302] = 51543, RECIP[1303] = 51503, else 0
                               ps = 24 at 0 dB (20 + P's 4 fraction bits; §7, §8)
x'     = sat27((fm >> 14) + x_poly)       to pcm_out's 512-tap FIR
```

x' = 64·P/16 for a constant P (P in 1/16 DAC LSBs) at Poly level 0 dB, so a poly voice has the
level it had when it was added to the 16-bit output (the shifts by OSD
level are in §7). The interval average puts a sinc(f / 768 kHz)
ahead of the 768 kHz sampling, so staircase images near multiples of
768 kHz are attenuated before they fold. The 27-bit saturation (32× full
scale) keeps pcm_out's multiplier at 27 × 17; outputs that large clip in
`pcm()` anyway. FM and poly now clip together after the filter, not at 16
bits before it.

The real hardware's reconstruction filter is [UNK]; the FIR stands in for
it, as for FM. Aliasing from PI > 1 (words skipped when pitched up) is the
hardware's own and stays.

## 3. HDL

### 3.1 `dev_poly.sv`: rate pass = mix + latch + step

One voice a clock, rows read at `cnt`, worked at `pv`. Per voice, beside the
rows: `lr_mem` (its line: the 64-bit DDR3 beat holding the DAC's word),
`dr_mem` (that beat's address and the word in it), `lval` (line holds the
beat), `dac_on`.

* mix: `lr_q[word]` × EVAL × L/R through the existing 3-stage multiply-
  accumulate when `dac_on`;
* latch: new address; same beat as the valid line → nothing to fetch;
  else a fetch {voice, beat} is queued (`fv_mem`/`fb_mem`, 128 entries,
  issued in order on `s_*`, data back in order into `lr_mem`);
* step as before.

After the last voice the sums go out as `p_valid`/`p_l`/`p_r`. A rate pass
starts only when the previous pass's fetches are back (`fetch_idle`), so
the mix never waits inside a pass. Passes run in time order (rate first
on a tie).

**Coherency.** A poly memory write (CPU FC 18, `dig_stm` imports, the clear
at reset) waits for `fetch_idle` and clears every `lval`; the next latch of
each voice re-fetches. A valid line therefore always equals memory, which
is what step 2 reads. `test_dev_poly` writes memory under sounding voices;
removing the invalidation makes it fail.

`ddram_word.sv`'s stream now returns the whole 64-bit beat.

**DDR3 load test** (OSD "DDR3 load test", status bits 55:54, `ftest`): in
each rate pass, voices whose DAC is off (every 4th, every 2nd or all) also
fetch a beat at a pseudo-random address in the first 4 MB and drop the
data. With 128 voices and "All voices" that is 12.9 M fetches/s, the worst
case above; the sound does not change. A .62 that cannot sustain it shows a
growing `P` count (real-time voices) and lag.

### 3.2 `poly_box.sv` (in `able_system`, between `dev_fm` and `pcm_out`)

Keeps voice time as `dev_poly` does; `dev_fm` exports each instant's tick
and offset (`inst`, `inst_d`). FM samples wait (8 deep) until the P they
need has come. With voices on CPU time (lockstep) 4 waiting hold the CPU
(`stall`, charged to STALL_POLY), which stops voice time, so the output
never depends on how long `dev_poly` takes. With voices on real time (M14)
a hold would not stop them, only add lag, so there is none: with 8 waiting
the oldest sample goes out with that P taken as P_cur and the P is dropped
when it arrives; `late` counts these, shown on the status line as `P` + its
low 3 hex digits (col 76; it wraps, so two looks tell whether it still
counts).

`dev_poly` runs its passes between the bursts of the poly memory clear
after reset, so voice time does not fall behind during it. (The first .62
build cleared first: 32 MB took long enough that `P` saturated at FFF and
the CPU hold added 30 ms of boot lag.) Two multipliers used in
turn, 8 clocks a sample. In `able_sys_top` (no `dev_poly`) `en` = 0: x' is
the FM part.

`pcm_out.sv` takes x' (27 bits) directly.

### 3.3 Cycle budget (clk_sys 50 MHz, 495 clocks per F0 tick)

| per F0 tick | clocks |
|---|---|
| rate pass, 128 voices, + 4 to drain the multiply | ~135 |
| envelope pass (every 4th tick) | ~33 avg |
| CPU D157 accesses | tens |

## 4. Memory throughput

A fetch is one 64-bit beat (4 words), so a voice reads DDR3 once per beat it
moves into, not once per step.

| case | reads/s |
|---|---|
| before M26: 48 kHz × sounding voices, 96 voices (project notes: 96 voices verified on .62) | 4.61 M |
| before M26, 128 voices | 6.14 M |
| M26, 128 voices, 50 kHz files at original pitch (PI 1, 50 kHz steps) | 1.6 M |
| M26, 128 voices at F0 with PI = 1 | 3.2 M |
| M26, 128 voices at F0 with PI = 2 | 6.5 M |
| M26, worst: 128 voices at F0 with PI ≥ 4 | 12.9 M |

PI ≥ 4 needs FREQ.NUM ≥ 6144 (2.25 octaves above a 50 kHz file's original
pitch). A stereo slave keeps its own line (it re-fetches its master's beat).
`ddram_word` takes a stream command every 2 clocks at most (25 M/s), ≤ 30
in flight; the DDR3 controller shared with the HPS and the scaler is the
[UNK] limit. Too little throughput shows as `late` (real-time voices) or a
slower CPU, never as wrong samples in lockstep.

### 4.1 Measured on the .62 (abdaf62, 128 poly voices, 4 × 32 MB)

`P` read twice, 30 s apart, at idle (real-time voices, HDMI scaler on):

| load test | extra fetches/s | `P` counted in 30 s | Underrun |
|---|---|---|---|
| Off | 0 | 0 | 0 |
| 1/2 voices | 6.5 M | 1 | 0 |
| All voices | 12.9 M | ~750–1450 (25–50/s; the 12-bit display may have wrapped) | 0 |
| All voices, Gymnopédie playing | 12.9 M less the sounding voices | ~47/s | 0 |

So the .62 sustains about 13 M random 64-bit reads/s: at the worst case
about 0.05 % of P values come late (each is replaced by the previous P for
one 9.9 µs step); at 6.5 M/s and below practically none. Multi-beat bursts
are not needed for realistic loads. From an earlier build that held the CPU
on lateness, a rate pass with 128 random fetches takes about 9.4 µs of its
9.9 µs tick. Side effects of the load test itself: at All voices, poly
memory writes wait for nearly full passes (a sample load added 2 s of lag);
with 128 voices, boot lag is the CPU waiting for the 128 MB clear (119 ms
without the load test, as before M26).

## 5. Verification

| check | result |
|---|---|
| `tests/sim/test_poly.py` `test_dac_output`, `test_record_skips_silence` | DAC timing, re-read, stereo slave, off |
| `tests/sim/test_pcm.py` `test_poly_box`, `test_poly_aliasing` | interval weights, start(), constant P → P; alias −124 dB re tone (was −13.9 dB) |
| `tests/hdl/test_board.py` `test_dev_poly` | HDL P(m) = Python in 9 configurations (bins, last bin, mono, distributor, load test on: 566k fetches vs 71k, same P), memory writes under sounding voices |
| `tests/hdl/test_board.py` `test_poly_box` | HDL x' = Python, 3000 instants × 5 seeds at the OSD level codes (0/0, 1/1, 2/2, 3/3, 0/3), random P latency, saturation |
| `tests/hdl/test_board.py` `test_pcm_limit` | HDL limiter = `sim/pcm.py` `Limiter`, 2 × 6000 samples from quiet to 2^21, on/off toggled |
| `tests/sim/test_pcm.py` `test_pcm_out_arithmetic`, `test_limiter` | one FM voice 8192 at +12 dB (2048 at 0 dB), each step 6 dB; limiter transparent below −1 dBFS, never above, hold, release to unity |
| .62, default image (64 voices, 36 MB) | boot Lag 0 (first build: 48.6 ms), Gymnopédie on FULL PIANO: Underrun 0, Overrun 0, `P` 002 all through (the two ticks in the 20 µs row clear after reset) |
| .62, 128 voices, load test | see §4.1 |

## 6. Unknown

* .62 sustained DDR3 random-beat rate with HPS + scaler load.
* Base-address parity of stereo files (whether a frame ever straddles a beat).

## 7. Output levels and limiter (#76)

**Problem.** Before #76, one FM voice at full level, hard-panned, reached
1/16 of full scale (−24 dBFS), set so a dense 32-voice FM chorale would
not clip (M23). A poly voice with a full-scale sample at full volume
reached full scale. Measured in the sim on SYN-5.3 (C4, velocity 100):

| sound | peak | RMS, first 0.5 s |
|---|---|---|
| W0 FM timbres 1-1-2 … 1-1-5 | −27 dBFS | −31 dBFS |
| FULL PIANO 5.7 (poly) | −12 dBFS | −26 dBFS |

A single FM note was hard to hear; poly was louder. The Bach chorale demo
on SYNCLAV-ORGAN 2. (32 FM voices) already peaked at −2.6 dBFS, so raising
FM with a hard clip would distort dense FM.

**SYN-5.3 does not set the balance.** FM `VOL` (0–255) and the poly
volumes (0–4095) are both computed from the same partial volume × volume
pedal (`MY.VOL · AVOL`; poly also × the sound file's volume field), each
to its own full scale (`352-SPLC:43,80-87`, `144-TIM3:945-953`). No factor
matches one to the other; on the instrument the analog output stages and the
user's mixer did (the 9600's levels are [UNK]).

**OSD (status bits 56–60, 0 = the defaults):**

| item | codes 0 / 1 / 2 / 3 | shift (sim `fm_shift`, `poly_shift`) |
|---|---|---|
| FM level | **+12** / +18 / +24 / 0 dB | FM sum `>>>` 12 / 11 / 10 / 14 |
| Poly level | **+6** / +12 / 0 / −6 dB | poly `y·RECIP >>>` 23 / 22 / 24 / 25 (P has 4 fraction bits, §8) |
| Limiter | **On** / Off | — |
| Reverb (§9, status bits 62–63) | **Off** / Room / Hall / Plate | — |
| Reverb mix (bits 64–65) | **−12** / −6 / −18 / 0 dB | wet gain |
| Reverb tone (bits 66–67) | **8 kHz** / 5 kHz / 3 kHz / Full | high cut on the reverb's input |

0 dB is the level before #76. At the defaults one FM voice is 1/4 of full
scale; at +24 dB it is full scale, about the 9600 figure the user quoted
(single voice −1 dB peak, +3 dB per doubling of voices; source document
not in the repo, [UNK]). +3 dB per doubling is uncorrelated voices adding
in power: 32 voices average 15 dB over one, which a 16-bit output holds
only through the limiter (so the 9600's −1 dB is presumably an analog
reference with headroom above it [INF]). Steps are whole 6 dB so a level
is a shift (`poly_box.sv`).

**Limiter** (`pcm_limit.sv` = `sim/pcm.py` `Limiter`, after `pcm_out`'s
filter, which now gives v unclipped, |v| < 2^21). One gain G/2^24 for both
sides; per 48 kHz sample, p = max(|vl|, |vr|):

```
if p·G > T·2^24:  G = floor(T·2^24 / p); hold = 960        (attack, instant)
out = (v·G + 2^23) >>> 24                                   (|out| <= T)
then: hold > 0: hold -= 1;  else G = min(2^24, G + ((2^24 − G) >> 12) + 1)
T = 29204 (−1 dBFS); hold 20 ms; release time constant 4096 samples (85 ms)
```

Below −1 dBFS with G at unity the output is v, bit for bit. Off: v clipped
to 16 bits, as before. The attack has no look-ahead, so the first sample
over the threshold sets the gain; the 20 ms hold keeps low notes from being
modulated within a cycle. It costs one multiplier and about 45 clocks a sample
(pcm_out gives one every 512 or more).

**Renders** (`tools/demo.py render`) take `--fm-level`, `--poly-level`,
`--limiter-off` and report the peak before the limiter and the samples
over −1 dBFS. Chunks render unlimited (`render_frames(limit=None)`) and the
limiter runs once over the joined render, from the recording start (the core's
starts at reset; the two agree once the gain is back at unity).

## 8. Mix precision (#82)

On the instrument each poly voice's 16-bit DAC gets the whole word, and
EVAL and the volumes act in the MDACs (analog), so the DAC's quantization
is attenuated with the signal. Before #82 the model floored each voice's
`dac × EVAL × volume` (40 bits) to the DAC's LSB (`>> 24`) before summing:
a fixed error per sounding voice, whatever its volume.

Measured (sim, PolyBox + FIR at the default +6 dB; voices sines at
different pitches, EVAL × volume ≈ −40 dB; error = model − exact mix):

| voices | `>> 24` floor (before) | 4 fraction bits, rounded (now) |
|---|---|---|
| 32 | noise −84.1 dBFS, DC −32 LSB | noise −108.3 dBFS, DC 0 |
| 128 | noise −78.2 dBFS, DC −128 LSB (−48 dBFS) | noise −102.3 dBFS, DC 0 |

The DC was a step each time voices started or stopped. Now
`mix(e) = (e + 2^19) >> 20` per voice and side (`sim/devices/poly.py`
`mix`, `dev_poly.sv` `m_pl`/`m_pr`); P carries 4 fraction bits, so
`poly_box` keeps P at 32 bits (was 27) and shifts 4 more. 128 voices at
full scale and volume need 2^27 per side: within 32 bits.

## 9. Output reverb

**[CHOICE]**: the Synclavier had no reverb; studios used outboard units
(Lexicon, EMT). OSD Reverb adds one for listening on MiSTer. It is Off by
default, and Off passes `pcm_out`'s samples through bit for bit, so the
output, the tests and the renders are as before.

**Place.** `hdl/dev/pcm_reverb.sv` (= `sim/pcm.py` `Reverb`, bit for bit)
sits between `pcm_out` and the limiter (`able_system.sv`), so the limiter
catches the wet build-up and renders (`tools/demo.py render --reverb N
--reverb-mix M --reverb-tone K`) include it.

**Algorithm.** An 8-line feedback delay network at 48 kHz, constants from
`tools/gen_pcm_reverb.py` (`sim/pcm_reverb.py`, `hdl/dev/pcm_reverb.svh`):

```
x = sat20((vl + vr) >>> 2)                      mono, −6 dB
tone: two stages s += ((x + x_prev)/2 − s) · c    (high cut; Full bypasses)
predelay, then 4 series all-passes (241, 173, 409, 307 samples; g 0.6, 0.6, 0.5, 0.5) → d
lines i = 0..7:  y = line_out[i] read at L[i] + 0..8 samples (triangle, 1.0 – 1.9 Hz, interpolated)
                 lp[i] = y + (lp[i] − y) · b[i]                  (one-pole damping, Jot)
h = Hadamard8(lp)                                (adds only)
line_in[i] = sat20(h[i] · g[i] ± d/2),  g[i] = 10^(−3·L[i] / (T60·48000)) / √8
e = h − tc · h_prev                              (tonal correction, Jot's E(z))
out = sat22(vl + e[1] · mix), sat22(vr + e[2] · mix)   (two orthogonal Hadamard rows)
```

Products are `/2^15` truncated toward zero; the damping is written as
`y + (lp − y) · b` so the truncation pulls `lp` onto the line output and
the tail decays to 0 (as `lp += (y − lp) · c` it could stick at ±1 and
hold a few LSB of DC). The wet output rounds. One delay memory of
22528 × 20-bit words (44 M10K) holds the predelay, the all-passes and the
lines: a pointer decremented each sample, a line written at `p + B` and read
`L` samples later at `p + B + L`, addresses mod 22528 (a compare and a
subtract, so the memory is the size the lines need, not the next power of
2). Types use the same regions (Room reads shorter).

**Jot's design** (JOS, *Physical Audio Signal Processing*, FDN
reverberation): each line's damping pole `b[i] = ln10/4 · log10(g'[i]) ·
(1 − 1/α²)` (`g'` the line's gain before 1/√8, α = T60 at 24 kHz / T60
at DC: Room 0.39, Hall 0.29, Plate 0.44), so every line loses the same dB
per second at each frequency: one coefficient for all lines, as before, let
Hall's longest line ring on at the top twice as long as its shortest.
The tonal correction `E(z) = (1 − tc·z⁻¹) / (1 − tc)`, `tc = (1 − α) / (1
+ α)` (the 1/(1 − tc) folded into the mix gain), gives back the highs the
faster-decaying modes take out of the tail's colour. The lines are 1.4
times the first version's (Hall 1669 – 3359 samples) so each type meets
the mode density requirement, total delay ≥ 0.15 · T60 · 48000 (Hall
19506 ≥ 18720 samples; it had 13934). This replaced the first damping
after listening (A/B against a Householder matrix, no diffusers, and each
change alone: Jot's damping with the longer lines sounded least metallic).

**Ringing.** The first version (all-pass g 0.75/0.625, fixed reads) left
narrow high modes ringing on in the tail: in Room's impulse response, 9
bins between 2 and 14 kHz stood more than 6 dB over their neighbours all
through 0.15 – 0.45 T60, e.g. 5.2, 7.5, 11.7 kHz (Hall had some at 4.6 and
11.7 kHz); an exponentially decaying noise has none. Lower all-pass gains
(0.6/0.5) remove most of them, and the modulated reads (each line's delay
swept 0 – 8 samples by its own triangle, about 1 cent of pitch wobble) the rest: no
such bin in any type. The interpolation also damps the high band a little.

**Tone.** Each stage is a one-pole with a zero at 24 kHz; `c` puts the
two stages' −3 dB point at the OSD frequency (8 kHz default: −6.4 dB at
10 – 14 kHz on Hall, 5 kHz: −12.1 dB, 3 kHz: −19.8 dB). The network sees
the filtered input, so the whole wet signal is cut, early and late.

| type | predelay | lines (samples) | T60 design (no damping) | α | measured broadband / above 4 kHz (tone Full) |
|---|---|---|---|---|---|
| Room | 8 ms | 653 – 1319 | 0.8 s | 0.39 | 0.64 s / 0.54 s |
| Hall | 25 ms | 1669 – 3359 | 2.6 s | 0.29 | 1.93 s / 1.53 s |
| Plate | 4 ms | 1327 – 2687 | 2.0 s | 0.44 | 1.56 s / 1.38 s |

Mix 0 dB: with tone Full, an impulse's wet energy per side equals its dry
energy (within 0.1 dB measured); the default −12 dB is a quarter of that.
A lower tone takes some energy away with the highs. L/R correlation of the
wet impulse response is under 0.05.

**Changes.** The type, mix and tone are taken with each sample. A change to
Room, Hall or Plate (or reset in one) clears the delay memory: that sample
and the next 87 pass dry while 256 words a sample are zeroed (1.8 ms). A
change of mix or tone only changes the gain or the filter.

**Cost.** One multiplier (24 × 18), about 135 clocks a sample (a clear
256); `pcm_out` gives one every 512 or more. 44 M10K.

| check | result |
|---|---|
| `tests/sim/test_pcm.py` `test_reverb_*` | tables generated; Off = dry; T60 per type within 10 % of design without damping or modulation, high band shortest with them; mix 0 dB wet energy = dry ±0.5 dB; decorrelated sides; tail within 2 LSB; mode density met and every line's T60 at DC within 1 %, at 24 kHz within 10 % of the others (one coefficient for all: 2:1); no ringing bin in any type (the first design's Room: 5 or more); each tone's response on Hall within 0.5 dB of its design; full-range noise stays within 22 bits and under −1 dBFS after the limiter |
| `tests/hdl/test_board.py` `test_pcm_reverb` | HDL = `sim/pcm.py` `Reverb`, 2 × 30000 samples (the pointer all the way round the memory; impulses, noise to 2^21, type, mix and tone changes, clears), inputs 300 clocks apart |
