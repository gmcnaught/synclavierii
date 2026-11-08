# Release L real-time program under the simulator (M2)

Milestone M2 in [`plan.md`](plan.md): run the Release L real-time program
(RTP) `ORK-LM` and recover the register maps of the devices it drives.
This page covers **M2.1** (running it and logging every device access).

## Run it

```bash
python3 -m sim.rtp IMAGE.simg --seconds 10 --log out/ork-lm-io.csv
```

About 20 s of wall time for 10 simulated seconds. Terminal output (VT100)
is printed live:

```
WELCOME TO THE SYNCLAVIER
DIGITAL MUSIC SYSTEM
lqqqqqqqqqqqqqqq…k            (a box drawn with the DEC line-drawing set)
```

The CSV has one row per device access by the RTP: `time_ns, pc, rw,
device, value` (octal). Terminal and external-memory transfers are left out
by default (`--quiet-devices`). `--rtp ORK-LFM` runs the other RTP.

## How it is started

Release L is a Winchester system (see
[`release-l-image.md`](release-l-image.md) §3.4): `PLAY` needs the SCRIPT
compiler, which is only inside the `.SYSTEM` install archive. `sim/rtp.py`
therefore lets MONITOR do what it does for any `RUN` and only swaps the
file:

1. Boot MONITOR from `03-SYSTD` and type `ENTER F0:`, `OLD CONFIGUR`, `RUN`.
2. MONITOR sets the run state in high core (magic number at
   `MEM.SIZ` − 138, run status, memory-size words) and enters the `.LD-6`
   loader (entry 1, 2 or 3).
3. There, the RTP (both floppies' parts joined, headers dropped) is staged
   in external memory and the CPU enters the loader's ECOPY entry instead.
   The loader copies the object code (0–114564) to core, copies the
   high-core configuration into it, moves the 519-sector swap file to the
   top of external memory, passes its address in R4, and jumps to 0.

The staged copy has to lie below the swap file's final place, so the
system gets 2048 sectors (512K words) of external memory.

## What it needed

| Problem | Evidence | Change |
|---|---|---|
| System configuration says **Model C** (processor type 2) on every boot disk | options 141031 / 141011; `CONFIGUR` shows "Model C" | Boot writes Model B into MONITOR's configuration (`processor="B"`) to match the CPU |
| ORK-LM tests for Model C: `IM(0) TO R0; IM(0) TO ADD0; IM(5) TO ADC0; R0 TO LOA0`, and if R0 ≠ 0 enables `D10` repeat loops (flag at 123727) | swapped procedure at the swap area (114565) | Model B: destinations 270–277 do nothing **[HYP]**; ADC/SBB only with `cpu.model = "C"` |
| Divides with only `R0 TO D5; IM(20) TO D7` (no D4 write) | bitmap routine at 012233; NED `XPL.h`: "write to d5 cleared d4" | D5 write clears D4. With a stale D4 the quotient was wrong, the bitmap routine flipped bits in code, and the program jumped into data after ~2 s |
| Reads/writes synthesizer registers MONITOR never uses | — | Probe mode: stubs return 0 for unknown reads; a fallback device answers unclaimed numbers |

## Device accesses (first 10 simulated seconds)

Counts from `out/ork-lm-io.csv` (RTP start = MONITOR hand-off at 3.32 s).
Values are octal, most frequent first.

| Device | R/W | Count | Distinct PCs | Common values | Notes |
|---|---|---:|---:|---|---|
| D3 | R | 442,139 | 3 | 0, 1 | polled for clock ticks (interrupts off) |
| D3 | W | 1,755 | 7 | 0 | acknowledge |
| D4 / D5 | R/W | 5,073 / 13,563 reads | 20 / 88 | | multiply/divide |
| D6 / D7 | W | 11,414 / 2,581 | 54 / 28 | 14, 177473 / 71, 100, 20341 | multiply / divide starts |
| D100–D104 | R/W | 462,042 status reads | | | reads its data files from F0 (at ~3.67–4.35 s) |
| **D130** | R | 7,035 | 3 | 0 (5,875), 1 (1,160) | keyboard data |
| **D130** | W | 92 | 3 | 0, 1, 100, 401 | from 7.3 s: panel lights? |
| **D131** | W | 12,139 | 20 | 20, 260, 105, 100 | keyboard/panel control; 105 = "check keyboard type" (MONITOR) |
| **D160** | R | 2,525 | 8 | 0 | main loop tests bit 1 (`D160 TO LOA0; IM(2) TO AND0`, 021475) and compares with the last value |
| **D160** | W | 1,175 | 2 | 0 (1,160), 20, 40, 60 | channel select |
| **D161** | W | 1,159 | 1 | 0 | function select |
| **D163** | R/W | 61 / 74 | 6 / 8 | W: 2, 3, 6, 22 | not modelled (probe) |
| **D164** | W | 4 | 4 | 0, 1, 2, 3 | from 7.6 s |
| **D165** | W | 4 | 4 | 372, 0, 10200 | from 7.6 s |

D162 (FM data) is not written in this window. No other device numbers are
touched.

## Register maps (M2.2)

The devices above are decoded from NED's 1986–89 RTP source and checked
against this log:

* [`devices/d130-original-keyboard.md`](devices/d130-original-keyboard.md):
  D130/D131 clavier scan (negative logic), panel buttons/lights, display.
  With the M2.1 probe every key read as held; the model now reads idle.
* [`devices/d160-fm-interface.md`](devices/d160-fm-interface.md): D160
  channel / D161 function / D162 data; D160 read bit 0 = channel exists
  (voice detection), bit 1 = external clock (the main-loop poll), bits
  2–7 = switches; D163 = A/D converter (the writes 2, 3, 6, 22) and clock
  out.
* [`devices/d164-control-voltages.md`](devices/d164-control-voltages.md):
  D164 DAC select, D165 value (filter CVs, keyboard pitch/gate/trigger).

With these models ORK-LM detects 8 voices ("9 VOICES" on its screen),
loads four 256-point wave memories and runs with no unmodelled device
access. **A key press does not yet produce FM writes**; the next step is
recalling a timbre, which needs the panel's logical button map.
