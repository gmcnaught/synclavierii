# D160–D163: FM synthesizer interface and old-panel inputs

The original Synclavier II FM synthesizer is programmed through three
write registers; the same device numbers also read the old panel's
switches, the external clock input and an A/D converter.

Model: `sim/devices/synth.py` `FMInterface`. Tests: `tests/sim/test_synth.py`.

## Registers

| Device | Write | Read |
|---|---|---|
| D160 | channel number (`CHA`) | bit 0: the selected channel exists, or, with function 12 selected, 0 = its interpolator has reached the limit (see below); bit 1: external clock input; bits 2–7: six switches (`SW`, "switch register - old panel") |
| D161 | function code (`FUN`) | — |
| D162 | 8-bit data (`DAT`) for (channel, function) | — |
| D163 | `2 + 4·ch`: select A/D channel; `3`: start the next conversion; `1`: toggle the external clock output ("15 ms pulse") | A/D result (`AD`, "AD converter - old panel") |

A/D channels: 0 knob, 1 ribbon, 2 pitch wheel, 3 pedal 1, 4 pedal 2
(`SCAN.ORK.ANALOG.INPUTS` reads them in the order 0, 1, 4, 3, 2).

## Channels and function codes

"A channel number (0–63 for quad synth systems) is written to device 160.
A function code is then written to device 161. There are 16 function
codes, some of which are not used. An 8-bit data word is then written to
device 162." Each voice has two channels: **even = modulator, odd =
carrier**. One voice card holds 8 voices (16 channels).

| Code (octal) | Both channels | Even (modulator) | Odd (carrier) |
|---|---|---|---|
| 0 | `INC` increment | | |
| 1 | `NNU` note number | | |
| 2 | `ONU` octave number | | |
| 4 | `TIM` timbre bits (`32 + n` selects wave memory n for loading) | | |
| 6 | `ZMA` zero the memory address register | | |
| 7 | `MEM` wave memory data (successive bytes) | | |
| 10 | | `IDIV` index interpolation divisor | `EDIV` envelope divisor |
| 11 | | `IADD` index adder number | `EADD` envelope adder number |
| 12 | | `ILIM` index limit | `ELIM` envelope limit |
| 13 | | `ISHC` index shift count | `VOL` volume |

Silence (MONITOR `SILENCE.VOICES`, and ORK-LM at start): for every
channel, functions 0–13 get `255, 255, 0, 0, 0, 0, 0, 0, 255, 255, 0, 0`.

## Voice detection

ORK-LM probes one channel per card: for `ch` = 0, 20, 40 … 360 it writes
`ch` to D160 and tests bit 0 of a D160 read; the highest present card
gives the channel count, and voices = channels / 2. NED's later
`600-INIT` does the same per voice (`WRITE(CHA)=SHL(IVOICE,1); IF
READ(CHA) THEN /* CHANNEL EXISTS */`). The model's `voices` (default 8,
CHOICE) sets how many channels answer. ORK-LM's start screen shows the
count plus one ("9 VOICES" for 8).

## What Release L ORK-LM does at start (8 voices)

1,224 D162 writes in the first 6 simulated seconds:
* silence channels 0–17 (12 functions each, values above);
* load four 256-entry wave memories through channel 1: `TIM` = 32, 33,
  34, 35, each followed by `ZMA` = 0 and 256 × `MEM` (1,032 `MEM` writes
  in all). These are the 256-point waveforms of the card analysis.
* the main loop reads D160 about 117,000 times a second (bit 1, the
  external clock) and the switches every scan.

**Channel words.** ORK-LM writes whole "channel words" to D160 (NED
`SYNLITS:QUELITS`): `[4 bits state][4 bits wave memory 8–15 used for
splicing][8 bits channel 0–255]`. Free channels are stored as
`I \ SHL(8 + (SHR(I,1) & 7), 8)`, so voice n's channels carry wave memory
8 + n: e.g. `4001` = channel 1, `5407` = channel 7 (memory 13). The model
takes the low 8 bits as the channel and logs the whole word; whether the
hardware uses bits 8–11 is open.

## Limit status (bit 0 with function 12)

NED (`144-TIM3`, `352-SPLC`) and Release L ORK-LM (PC 076606–076614)
select a channel, write function 12 (`ELIM`/`ILIM`), write the limit
twice and read D160: "GET 0 IF LIMIT REACHED". The model returns 0 when
function 12 is selected and the channel's interpolator equals the limit,
otherwise the channel-present bit. **[INFERRED]**; details and the
interpolator in [`../fm-voice.md`](../fm-voice.md#interpolators-envelope-and-index).

## A note (Release L ORK-LM, timbre 0 of bank 0, key C4)

Timbre 0 has one partial, so C4 uses one voice (modulator channel word
`4000`, carrier `4001`). Note-on: modulator `ISHC` = 203; carrier `TIM` =
44, `VOL` = 375, `ONU` = 1, `NNU` = 300, `INC` = 176 (523.3 Hz, see
[`../fm-voice.md`](../fm-voice.md#pitch-verified)), `EDIV` = 177777,
`EADD` = 377, `ELIM` = 372. While the key is held, `VOL` = 375 is
rewritten about 345 times a second. All values fit in 8 bits except
`EDIV` = 177777 (−1; low byte 377).

**Correction:** an earlier version of this page reported 16-bit, byte-
swapped pitch words and four partials for this note. Those came from a
fault in the simulator's RTP hand-off: MONITOR's `PLAY` file pointers were
not set, so ORK-LM loaded floppy sectors 0–12 instead of `.STAB-6` as its
tables. `sim.rtp` now runs `SET RTP` + `PLAY` first.

`python3 -m sim.rtp IMAGE --swap-f0 06-TIMBD --buttons bank.0,timb.0
--keys 48 --fm-log out.csv` records every write with its time.

## Evidence

* NED `Able/SYNLITS/FCODLITS` (`3b6fb1ca8483`, 9/15/86): registers,
  function codes, the comment quoted above, `AD`/`SW` (commented out).
* `Able/SYNRSOU/05-BUTT/076-OLDI` (`9c3914be9a6e`): switches
  (`READ(SW)&"374"`, six switches from bit 2) and the A/D sequence.
* `Able/SYNRSOU/04-SEQ/162-SEQ2` (`adc13e417b2c`), `10-INT/144-TIM4`:
  `CLOCK.DATA=READ("160")&2`; `WRITE("163")=1` toggles the clock out.
* `Able/SYNRSOU/08-INIT/600-INIT` (`3f5ebc3a9b73`): channel-exists probe.
* Release L ORK-LM run (`sim.rtp`): the D163 writes `2, 3, 6, 22` (A/D
  channels 0, 1, 4 and start), the per-card probe at 115621, and the
  start-up writes above. **[OBS]**

## Open

* D160 write `4001`; switch assignments of the six switch bits.
* All registers are decoded in [`../fm-voice.md`](../fm-voice.md) (M3.1a);
  open hardware details are listed there.
