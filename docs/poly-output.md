# Poly output: F0-rate mix and anti-aliasing (M26)

Code: `sim/devices/poly.py` (P(m)), `sim/pcm.py` (`PolyBox`, `x_in`,
`Limiter`), `hdl/dev/dev_poly.sv`, `hdl/dev/poly_box.sv`,
`hdl/dev/pcm_out.sv`, `hdl/dev/pcm_limit.sv`, `hdl/board/ddram_word.sv`.
Output levels and the limiter: §7.

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

1. **Mix.** `P(m) = Σ_v route(dac_v × EVAL_v × {L,R}cur_v >> 24)`, the gains
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
x_poly = y·RECIP[d] >> 20      RECIP[1302] = 51543, RECIP[1303] = 51503, else 0
x'     = sat27((fm >> 14) + x_poly)       to pcm_out's 512-tap FIR
```

x' = 64·P for a constant P at Poly level 0 dB, so a poly voice has the
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
| Poly level | **+6** / +12 / 0 / −6 dB | poly `y·RECIP >>>` 19 / 18 / 20 / 21 |
| Limiter | **On** / Off | — |

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

