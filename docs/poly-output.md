# Poly output: F0-rate mix and anti-aliasing (M26)

Code: `sim/devices/poly.py` (P(m)), `sim/pcm.py` (`PolyBox`, `x_in`),
`hdl/dev/dev_poly.sv`, `hdl/dev/poly_box.sv`, `hdl/dev/pcm_out.sv`,
`hdl/board/ddram_word.sv`.

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

x' = 64·P for a constant P, so a poly voice has the level it had when it was
added to the 16-bit output. The interval average puts a sinc(f / 768 kHz)
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
need has come; with 4 waiting it holds the CPU (`stall`, charged to
STALL_POLY), which in lockstep stops voice time, so the output never
depends on how long `dev_poly` takes. With voices on real time (M14) time
does not stop: with 8 waiting the oldest sample goes out with that P taken
as P_cur and the P is dropped when it arrives; `late` counts these, shown on
the status line as `P` + 3 hex digits (col 76). Two multipliers used in
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

## 5. Verification

| check | result |
|---|---|
| `tests/sim/test_poly.py` `test_dac_output`, `test_record_skips_silence` | DAC timing, re-read, stereo slave, off |
| `tests/sim/test_pcm.py` `test_poly_box`, `test_poly_aliasing` | interval weights, start(), constant P → P; alias −124 dB re tone (was −13.9 dB) |
| `tests/hdl/test_board.py` `test_dev_poly` | HDL P(m) = Python in 9 configurations (bins, last bin, mono, distributor, load test on: 566k fetches vs 71k, same P), memory writes under sounding voices |
| `tests/hdl/test_board.py` `test_poly_box` | HDL x' = Python, 6000 instants, random P latency, saturation |
| .62 | see the PR |

## 6. Unknown

* .62 sustained DDR3 random-beat rate with HPS + scaler load.
* Base-address parity of stereo files (whether a frame ever straddles a beat).
