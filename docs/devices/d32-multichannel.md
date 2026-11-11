# D32/D33: multichannel distributor ("Xpand system") — register map and model (M19)

Scope: what Release 5.3 (SYN-5.3, Model D) does with the multichannel
output distributor (8 or 16 individual outputs beside the stereo pair), and
the model in `sim/devices/multi.py` and `hdl/dev/dev_multi.sv` (with the
routing in `hdl/dev/dev_fm.sv` and `hdl/dev/dev_poly.sv`). Source: the NED
text of Release 5.3 in `out/ned53/` (paths relative to it).

Tags: **[OBS]** seen in source or in a run of the SYN-5.3 binary in the
simulator; **[INF]** inferred; **[CHOICE]** model choice; **[UNK]** not known.

## 1. Devices

| Device | Name (`SYNLITS/GLOBLITS:92-93`) | Write | Read |
|---|---|---|---|
| D32 | "DEVICE 32 DIGITAL IO MULTIPLEXOR" | subsystem select | not read by SYN-5.3; model: 0 [CHOICE] |
| D33 | "DATA PORT" | routing word (subsystem 0o21) | bit 0: present (0o20) / signal present (0o21) |

D51 bit 0x0800 (`D32_EXISTS`, Synclavier³ `AbleInterpreter.h`; `sim/devices/terminal.py`)
says the Xpand system may be there: `IF (READ("51")&2048)<>0` (`SYNRSOU/08-INIT/600-INIT:950`)
[OBS]. Without the bit SYN-5.3 never touches D32/D33 and the core answers
them with no SYN, as before.

Subsystems [OBS `600-INIT:953-955, 1008`]:

| D32 | Meaning | D33 read |
|---|---|---|
| 0o20 | "SELECT MULTI SUBSYS" | bit 0 = 1: "MULTI SYSTEM INCLUDED" |
| 0o21 | "SELECT MULTI PORT" (routing) | bit 0 = signal present (§3) |

`read_d33` reads twice "for better noise immunity" and takes either 1
(`600-INIT:938-946`) [OBS]. Other subsystem values are not used by SYN-5.3;
the model ignores D33 writes and reads 0 with them selected [CHOICE].

## 2. D33 routing word (subsystem 0o21)

```
bit 15     ignored [CHOICE] (the routing byte's 0o200 bit marks Direct-to-Disk
           outputs in THD.CUE.OUT, ROUTSOU:115-124; not a distributor route)
bit 14     on: switch the input to the output; 0: switch the input off
bits 13-8  output, 0-based (user output n = n - 1)
bits 7-0   input (one side of one voice: §4)
```

Evidence [OBS]:

* probe: `write(d33) = "040000" \ shl(7,8) \ ivoice` "turn on", then
  `shl(7,8) \ ivoice` (`600-INIT:1011, 1025`); "MAP INPUT TO OT7"
  `"040000"\SHL(7,8)\M`, "DISCONNECT INPUT V" `WRITE(D33)=M`
  (`600-INIT:1087, 1108`).
* note start: the track's routing word `THD.TROU` (left output in the high
  byte, right in the low, each `64 + output` with the on bit 64 = bit 14
  after the shift, 0 = muted) is or-ed with the voice's input from the
  multi→FM or multi→poly map: `WRITE(D33)=J\(SHR(READ(MD),8))` "ROUTE LEFT
  INPUT TO LEFT OUTPUT", `K\(READ(MD)&255)` the right (`144-TIM3:852-859,
  932-939`; FM: `307-STR7:802-811`, `303-SUB3:375-403`; playback
  `195-PLAY:155-213`; STM playback `STMPBSOU:242, 287`).
* note off: `WRITE(D33)=SHR(READ(MD),8)` "TURN OFF LEFT", `READ(MD)&255`
  the right (`301-SUB1:614-621, 652-659`).
* user numbers: `mcnum = 64+(mcnum-1)` for output `mcnum` (1..`MULTI.MAX`)
  (`ROUTSOU:599-614`); the keyboard routes to output 0 by default
  (`64+SHL(64,8)`, `131-SDF1:275`); TRACK ROUTING + TRACK VOLUME held and a
  track button b gives left b, right b + 1 (`174-PRF4:506-512`).

An input feeds at most one output: "off" writes give only the input, the
output field is whatever is there (0 or 7) [INF]. The model keeps, per
input, the output it is switched to or none; a switch to an output the card
does not have (>= its outputs) is "none" [CHOICE].

## 3. The connection analysis at start-up

`INIT.EXPAND.SYSTEM` (`600-INIT:924-1629`) [OBS]:

1. D32 = 0o20; D33 bit 0 → `MULTI.THERE = 1`.
2. If the info file (`INFOTHERE`, `.SINF-7`) holds data for the same poly
   hardware, `MULTI.MAX` and the two maps come from it and nothing is probed
   (`600-INIT:959-985`). Synclavier³'s W0 has no info file: SYN-5.3 analyses
   at every start-up and writes nothing to W0 [OBS: run below].
3. Otherwise "Analyzing Multi-Channel Connections..." on the terminal; all
   256 inputs switched to output 7 and off again, one per D3 tick.
4. FM: for each voice `IVOICE` whose channel exists, a DC wave on it and on
   `IVOICE XOR 1` (to cancel on the stereo outputs) at full volume and
   envelope limit, panned all left (ISHC 0): inputs `4i + ((IVOICE+1)&3)`,
   i = 0..63, each switched to output 7 in turn until D33 bit 0 = 1: that
   input is the voice's left (multi→FM map, high byte). The first time an
   input is found the outputs are counted: the same input to output 8k + 7,
   k = 1, 2, ... while bit 0 stays 1; `MULTI.MAX` = 8 + 8 × (outputs found).
   Then all right (ISHC 252) for the right input (low byte).
5. Poly (if a bin has memory): for each bin and channel `CHAN = IVOICE +
   64 × BIN`, the voice and `CHAN XOR 1` on with PSRCVOL left 4095 / right 0
   and PSELIM 4095, inputs `4i + (IVOICE&3)`; then right 4095 / left 0.
   Mono voice cards: the right side only (`600-INIT:1269`). SYN-5.3 has the
   "Optimized" branch (not `cj_changes`): disconnects are `WRITE(D33)=M`
   [OBS: D33 writes in the run].
6. A voice with no input found counts as an error; the info file is
   written only without errors. No output found: `MULTI.THERE = 0`.

Run [OBS, `tests/sim/test_multi.py`, `python3 -m sim.lockstep w0boot ...
--multi N`]: the analysis runs from 4.06 s to 4.48 s of simulated time;
`MULTI.THERE` (word 0o54725) = 1 and `MULTI.MAX` (0o54726) = 8 or 16 as
configured; every FM and poly voice side is found (129 positive reads with
32 FM + 32 poly voices: 128 sides + the count).

## 4. Model

### 4.1 Wiring of the inputs [CHOICE]

The probe fixes only the low two bits of an input. Input m = 4k + r:

| k | voice | side |
|---|---|---|
| 0-15 | FM voice 4 (k >> 1) + ((r + 3) & 3) | k & 1 (0 left, 1 right) |
| 16-63 | poly voice p = 4 ((k - 16) >> 1) + r = 32 × bin + channel | (k - 16) & 1 |

32 FM + 96 poly voices × 2 sides = 256 inputs, a 9600's full complement
[INF]. Poly voices from 96 up (the OSD allows 128) have no input: the
analysis counts them as errors and SYN-5.3 then does not write the info
file. Mono cards have no left DAC: their left inputs never carry a signal.

### 4.2 Signal present [CHOICE]

The detector answers for the input of the last D33 write: 1 when that
write switched it on to an output the card has and its voice side sounds.
"Sounds" is read from the voice's registers, not from its samples, so it
does not depend on time:

* FM voice v (v < voices present): volume (odd channel FC 13) ≠ 0, envelope
  limit (odd channel FC 12) ≠ 0, and pan (even channel FC 13 & 0o374)
  ≠ 252 for the left, ≠ 0 for the right (a side counts with more than
  4/256 of the signal; the probe's "all right" 252 leaves 4/256 on the left).
* poly voice: envelope limit (FC 36) ≠ 0 and that side's destination volume
  (FC 43 left, FC 41 right) ≠ 0. The on bit is not used: the probe's voice
  has a zero-length table and stops after one rate step in the model.

The analysis connects one input at a time, so "the last input" and "any
input on the addressed output" give the same answers there.

### 4.3 Audio: what the MiSTer plays

The MiSTer has two outputs. The OSD item **Outputs (multichannel)**
(`status[34:31]`) picks: **Stereo mix** (default: the instrument's stereo
outputs, unchanged by any routing [INF: the probe cancels each test voice on
the stereo outputs with its complement, so routed voices stay in the stereo
mix]) or one output pair **1-2 … 13-14** (outputs 15-16 need a fourth
status bit). With pair n selected, each voice side adds into the pair's left
if its input is switched to output 2n - 1 (1-based), its right if to 2n,
nothing otherwise; the selection is live (no reset). Without a distributor
the item has no effect.

* `sim/voice.py` `FMSynth.sample_int` and `sim/devices/poly.py` `_mix`:
  `devices.multi.route_pair` with `Distributor.pair`.
* `dev_fm.sv`: two 32 × 5-bit tag RAMs ({connected, output[3:0]}) read in
  the voice pipeline, four route bits per voice, one more pipeline stage
  (I) before the accumulators. `dev_poly.sv`: two 128 × 5-bit tag RAMs read
  with the voice row; the route bits travel with each read in flight (the
  factor FIFO grows from 36 to 40 bits). Mono cards in pair mode: the
  right side only.
* Level-detector state: 4 bits per FM voice and 3 per poly voice (flops),
  following the CPU's writes and the state load.
* `dev_multi.sv`: D32/D33, the input decode, the detector; a D33 write waits
  while the FM engine is busy with a sample instant already passed, as
  D160-D163 accesses do (the simulator mixes that sample before the write).

### 4.4 Configuration

| Where | What |
|---|---|
| `tools/w0_image.py --multi 8\|16` | state image with D51 bit 0x0800 and the outputs (device 3 index 16), name `-MC8`/`-MC16` |
| `sim/system.py make_system(multi=N)`, `sim/boot.py boot_from_w0(multi=N)` | `cpu.multi` |
| `python3 -m sim.lockstep w0boot ... --multi N [--outputs n]` | with `--poly --vpk`: `w0_multi_actions` (FM timbre, keyboard to outputs 3-4, a note, back to 1-2, a note); `--outputs` the pair in the `--audio` samples |
| `python3 -m sim.lockstep check ... --outputs n` | the board's OSD Outputs (`LOCKSTEP_OUTPUTS`) |
| OSD | Outputs (multichannel): Stereo mix, 1-2 … 13-14 |

The distributor has no load port: a state image must have it at power-on
(subsystem 0, nothing switched), which `_device_header` checks.

## 5. Open questions [UNK]

* Which inputs the real distributor wires to which voice cards, beyond the
  low two bits.
* Whether a voice switched to an individual output stays on the stereo
  outputs on the instrument (the model keeps the stereo mix unchanged).
* What the detector really measures (level threshold, which output).
