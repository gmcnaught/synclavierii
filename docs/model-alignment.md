# Model alignment: 3200 / 6400 / 9600 options on the MiSTer core

*Feature pass, 2026-11-10. Compares the core with the card options that
Release 5.3 (SYN-5.3) supports, and plans the remaining options that a
MiSTer can provide. Milestones continue from M15 in [`plan.md`](plan.md).*

Tags: **[OBS]** seen in NED source, binary or a cited document;
**[INF]** inferred; **[UNK]** not known.

## 1. Decision criterion

A Synclavier was a set of optional cards in one computer bin. The goal is
that every option SYN-5.3 can use, and that a MiSTer can stand in for, is
available in the core, and that the card complement can be set in the
same steps an owner upgraded in by adding or swapping cards (voice cards,
bins, memory, FM card sets), rather than only as the three factory
configurations. An option is in scope when (a) SYN-5.3 contains the
code for it (`SYNCOMS:SOME-VK` `inc.*` flags, below) and (b) its
input/output has a MiSTer equivalent (SD card, DDR3, MidiLink UART, stereo
audio, video, USB keyboard/mouse).

## 2. The three models

| | 3200 | 6400 | 9600 |
|---|---|---|---|
| Poly sampling voices | up to 32, **mono** voice cards [OBS muzines "Inside the Synclavier" (4578, 5607); SYSLITS `o#pvoice` "mono/3200 poly voices"] | 64 stereo, **2 bins** [OBS 5.3 manual via operator: "move sound files from poly bin 1 to poly bin 2"] | 32 stereo, expandable to **96** [OBS muzines 5607] = 3 bins [INF] |
| Poly memory | 4–32 MB [OBS] | 64 MB [INF] | 32 MB, up to 96 MB [OBS] |
| FM voices | 32 [operator] | 32 [operator] | 32 [OBS muzines 5607; operator] |
| Keyboard, button panel | none: MIDI keyboard, panel in software [OBS] | [UNK] | VPK (76 keys, velocity/pressure, breath) and real button panel [OBS] |
| Outputs | stereo + 8 individual, up to 16 [OBS] | [UNK] | stereo + 8, up to 16 [OBS] |
| MIDI | 2 in / 8 out module [OBS] | [INF same] | 2 × 8 [OBS] |
| SMPTE | reader/generator, VITC optional [OBS] | [INF same] | reader/generator [OBS] |
| Sampling (STM) | 2-channel A/D module [OBS] | [INF same] | [OBS] |
| Options | Direct-to-Disk 4–16 tracks, optical disk (2 GB WORM, 5" M/O), Kennedy tape, Macintosh II workstation [OBS] | | same + digital guitar interface [OBS] |

FM is in the core for every card complement. Muzines 5607 calls synthesis
9600-only; the core does not restrict it, since SYN-5.3 drives FM the same
way whatever the poly configuration.

SYN-5.3 is one program for all three ("Combine 3200, 6400 and 9600 RTP's",
`SYNCOMS:SOME-VK`, 1991). It finds the options by probing at start-up, so
a card complement is a machine setting, not a different program. The table
above is a reference for picking settings, not a set of presets.

SYN-5.3 build flags [OBS `SYNLITS/somelits` = `SYNCOMS:SOME-VK`]: poly,
VPK (`new.pan`), DTD, MIDI, mouse, multichannel, music notation, STM and
STM commands, timbre display, D130, FM, RS-422 protocol, keyboard maps;
**not** mono sampling (`inc.mono = 0`) or guitar (`inc.axe = 0`; the guitar
build is `SYN-5.3G`).

## 3. Feature matrix

"Core" is the state of `main` at `64b504f`.

| Option | Card / devices | Core | MiSTer route | Plan |
|---|---|---|---|---|
| Model D CPU, 64K internal + external memory | DSM+FPRM, D60–D63, D57 | done | — | — |
| D4567 multiply/divide, D3 clock | D4–D7, D3 | done | — | — |
| SCSI disks W0:, W1: | D24–D27 | done | SD images | — |
| Floppies | D100–D104 | done | SD images | — |
| FM voices, stereo pan | D160–D163 | 8/16/24/32 from the state image (default 8) | — | **M16**: OSD, default 32 |
| Poly voices, bins 1–4 | D154–D157 | sim: 4–32 voices per bin, 1–4 bins; HDL: 32 voices per bin fixed (`NUMV`), 1–4 bins; hardware verified 1 and 2 bins | DDR3 (224 MB) | **M16**: 4–128 voices in steps of 4 in the OSD |
| Poly memory per bin | poly memory cards | 32–224 MB in 32 MB steps (`--poly-mb`) | DDR3 | **M16**: 4 MB steps in the OSD |
| Mono / stereo poly voice cards | `o#pvoice` (options bit 0o200, one bit for the whole system) | stereo only | mono: right channel to both outputs | **M16** |
| VPK, button panel | D130/D131 | done (MIDI, Launchkey, on-screen) | — | M8a (Launchkey capture) |
| Breath controller | VPK input | done (CC 2) | MIDI | — |
| MIDI subsystem, 8 cards × 4 out / 1 in | D70–D73, subsystems 16–23 | done, 1 card | MidiLink (one port) | — |
| SMPTE reader | D70 subsystem 8, D51 bit 0x0100 | not modelled | MIDI Time Code in on MidiLink | **M20** |
| VT100 / VT640 terminal, D44 mouse | D50/D51, D44/D45/D54 | done | video, PS/2, USB mouse | — |
| Sample-to-memory, analog | SAFE A/D through the poly bin (FC 52–54, 58, 59; `polyadcs`) | not modelled | no audio input on a stock MiSTer | not planned (M18 covers recording) |
| Sample-to-memory, digital | interpreter native routines 64–76 (`-XPL/INTRPRTR`), D51 bit 0x8000 + D57 bit 0x4000 | not modelled | WAV file streamed from SD (later: USB audio through Main_MiSTer) | **M18** |
| Sound file import (no STM) | — | not available | offline tool → W1: image | **M17** |
| Multichannel distributor, 8/16 outputs | D32/D33, D51 bit 0x0800 | not modelled | 2 physical outputs: OSD selects stereo mix or one output pair | **M19** |
| Printer, music notation printing | D40/D41 (`o#d40`), `inc.music.notation` | not modelled | capture to an SD file, tool renders it | **M21** |
| Guitar interface | D134/D135, `SYN-5.3G` | not modelled | none: no practical input device to stand in for it | not planned |
| Keyboard filter/trigger CV | D164/D165 (`o#d164`) | writes accepted, discarded | no CV outputs; optional MIDI CC out | not planned |
| Scientific timer | D16/D17 | absent | SYN-5.3 measures it only when not interpreted [OBS `144-TIM2`]; absence has not blocked any tested path | check during M16 |
| Optical disk (LMS WORM, 5" M/O) | SCSI target (`OPTICAL`, `OPTLITS`, `INIT_OPTICAL_CONTROLLER`) | not modelled | SD image as a removable SCSI target | research spike S1: no optical images found (none in the Synclavier³ bundle) |
| Direct-to-Disk | separate 68K system on SCSI (`LODSOU`, `LOD-DTD*`), D34 GPI | not modelled | playback-only model feasible in principle (research log 2026-11-10) | research spike S2 |
| RS-422 comm processor (SyncNet, Macintosh link, MIDINet, termulator) | D115–D117, D57 bit 0x0010; 68K microcode loaded from disk | not modelled | needs a Macintosh-side peer | not planned |
| Macintosh terminal graphics | `g#macintosh` | not modelled | VT640 covers SYN-5.3's graphic screens | not planned |
| Mono sampling / sample-to-disk (Release L era) | D66/D67 (`o#d66`) | not modelled | SYN-5.3 has `inc.mono = 0` | not planned |
| Kennedy / SCSI tape backup | `TAPE*` | not modelled | W images already back up | not planned |

## 4. Milestones

Ordered by value per cost. Each needs the usual chain: simulator model,
HDL, board lockstep, CI build, .62 run.

### M16 — card complement in the OSD

Instead of 3200/6400/9600 presets, an OSD **Hardware** page sets the
cards, in the steps an owner upgraded in. Changes apply on the next reset
(a cold boot, as when cards were swapped with the power off), because
SYN-5.3 probes the hardware only at start-up.

| OSD item | Values | Upgrade step on the instrument |
|---|---|---|
| Poly voices | 4, 8, … 128 | voice cards in steps of 4 [OBS muzines 4578: "4 … expandable to 32 in steps of 4"]; bins fill in order: 32 per bin, the last bin gets the remainder (e.g. 72 = 32 + 32 + 8, 3 bins) [CHOICE] |
| Voice cards | stereo / mono | `o#pvoice`, one bit for the system [OBS SYSLITS]; mono = a 3200's cards, SYN-5.3 pans hard right [OBS `195-PLAY:174-178`], the core copies right to left |
| Poly memory per bin | 4, 8, … 32 MB; "max" = 224 MB ÷ bins | 4 MB steps [OBS muzines 4578]; 32 MB per bin matches a 9600's 96 MB in 3 bins [INF] |
| FM voices | 8, 16, 24, **32** (default) | all three models had 32 [operator]; the smaller sizes are the Synclavier II upgrade steps, one card set per 8 voices [secondary source: Wikipedia] |

Existing on/off cards (MIDI card, VT640 + mouse, W1:) stay as they are
today; M19–M21 add theirs to the same page.

Work:
* **State-image overrides.** The SST stays the computer as booted; the
  OSD values replace its device-configuration fields at load (poly bins,
  voices, sectors; FM voices; D51/D57 bits; MONITOR configuration word 17
  for `o#pvoice`, whose address `w0_image.py` records in the SST header).
  The same override function in `tools/state_image.py` serves the
  simulator, so the lockstep still compares one machine.
* **HDL:** poly voices per bin from the state image (`dev_poly` has
  `NUMV` fixed at 32; PSNUMV reads `N/4 | 0x10 | (N>16 ? 0x20 : 0)`
  [INF, poly-synth.md §4]; the mix skips absent voices); mono copy in
  the mix. FM needs no HDL change (`dev_fm` already takes 8–32 from the
  state image); `w0_image.py` default becomes 32.
* **Hardware runs:** 3 and 4 bins on .62, which were never run there.
* **Accept:** for 4, 36, 64, 72, 128 voices, mono and stereo, 4 and 32 MB:
  SYN-5.3's Main Menu bin lines and the VPK voice total match the OSD;
  board lockstep for 36 and 72 voices; on .62 a chord over all bins with
  0 underruns. Measure DDR3 read bandwidth first: M15 fitted 64 voices per
  48 kHz sample; 96–128 is [UNK].
* Risk: 128 voices may not fit the DDR3 budget at real time; then the OSD
  stops at the measured limit.
* [UNK] whether SYN-5.3 accepts a bin with fewer voices than the bins
  before it; `POLYNUMVS` is kept per bin (`600-INIT:964-967`), so likely.

### M17 — sound file import (WAV/AIFF → NED sound file)

* `tools/sound_import.py`: writes catalog type 5 files (header,
  symbol table, data; [`poly-synth.md`](poly-synth.md) §5) into a W1:
  image; mono/stereo, sample rate, loop points from WAV `smpl`.
* **Accept:** SYN-5.3 lists and loads the file into a bin, it plays at the
  right pitch, round trip `ned_disk.py` extract = input samples.
* This is the main route for user samples, since a stock MiSTer has no
  audio input.

### M18 — digital sample-to-memory

* CPU: trap the native routine call (`IM(n) TO RTNV`, relative transfer
  *never*, [`instruction-set.md`](instruction-set.md)) for routines 64–76;
  every other routine stays a no-op, as on hardware.
* State image: D51 bit 0x8000 and D57 bit 0x4000 (SYN-5.3 then offers the
  digital record device, `STDRSOUD:337-353`). D57 bit 0x8000
  (interpreter) stays clear.
* Source: a WAV file chosen in the OSD, streamed over `ioctl` into a FIFO;
  `do_import` writes 256/512 samples to memory, `lmax`/`rmax` feed the
  level meter.
* **Accept:** STM screen RECORD captures the WAV, saved sound file = WAV
  samples bit for bit (sim and .62).
* Later, out of tree: USB audio input in Main_MiSTer feeding the same FIFO.
* [UNK] where routines 64–76 take arguments and return values (registers
  per the XPL native calling convention); read `pass2.cpp`/`pass3.cpp`
  first.

### M19 — multichannel distributor (D32/D33)

* Model the probe `600-INIT:950-1030`: select subsystem 0o20, D33 bit 0
  = "signal present"; answer from the voice → output map, so the
  analysis finds 8 or 16 outputs (`MULTI.MAX`).
* Audio: per-voice output number kept with the mix; OSD "Outputs":
  stereo mix (default) or one output pair.
* **Accept:** "Analyzing Multi-Channel Connections" completes with 8/16
  outputs; routing a track to output 3 and selecting pair 3/4 plays only
  that track.

### M20 — SMPTE reader from MIDI Time Code

* D70 subsystem 8: status (bit 8 data available), D72 seconds/frames,
  D73 hours/minutes from MTC quarter frames received on MidiLink;
  D51 bit 0x0100.
* First check: whether SYN-5.3 already chases MTC through the MIDI card
  (d70 doc lists MTC only as sync *out*). If it does, M20 drops to a note.
* **Accept:** SYN-5.3 sequencer chases a DAW's MTC.

### M21 — printer port and music notation printing

* D40/D41 serial printer port → capture file on SD (`games/Synclavier/print/`).
* `tools/print_render.py`: render the captured stream for the configured
  printer type (`p#printronix`, `p#la34`, …; SYSLITS) to PNG/PDF.
* **Accept:** a printed score from the music notation screen renders
  legibly.

### Research spikes (no build until they pass)

* **S1 optical disk:** find NED optical images; if any exist, a removable
  SCSI target from an SD image.
* **S2 Direct-to-Disk playback:** reduced model (playback of existing
  projects), per the 2026-11-10 research note; SD throughput (~1.6 MB/s)
  against 16 tracks at 44.1/48 kHz.

## 5. Not planned, and why

| Option | Reason |
|---|---|
| Analog STM (SAFE A/D) | no audio input on a stock MiSTer; M17/M18 cover sampling |
| D115 SyncNet, Macintosh link, termulator | needs a Macintosh peer and its software |
| Macintosh terminal graphics | VT640 covers SYN-5.3's graphic screens |
| D164 CV/gate outputs | no CV hardware |
| Mono sampling (D66/D67), sample-to-disk | not in SYN-5.3 (`inc.mono = 0`) |
| Guitar interface (D134/D135, `SYN-5.3G`) | no practical input device to stand in for NED's guitar hardware |
| Tape backup | SD images replace it |
| Direct-to-Disk recording | separate 68K system, no firmware, no audio input |

## 6. Unknowns that change the plan

1. The FM card-set size below 32 (8 voices per set, Synclavier II) is from a secondary source.
2. DDR3 bandwidth for 96–128 poly voices (decides the top OSD value).
3. Whether a part-filled bin may follow full ones (M16 fill order).
4. Native routine calling convention for M18.
5. Whether SYN-5.3 chases MTC on the MIDI card (decides M20).

## Sources

* NED source (`jbemond/Software`, [`sources.md`](sources.md)):
  `-XPL/SYSLITS`, `-XPL/INTRPRTR`, `SYNLITS/GLOBLITS`, `SYNLITS/CPLITS`,
  `SYNLITS/somelits`, `SYNRSOU/08-INIT/600-INIT`, `610-INI1`,
  `SYNSOU/STMMOD/STDRSOUD`; `Code/Includes/Able Interpreter/AbleInterpreter.h`
  (D51/D57 bits).
* "Inside the Synclavier", Music Technology / Sound on Sound, via
  muzines: <https://www.muzines.co.uk/articles/inside-the-synclavier/4578>,
  <https://www.muzines.co.uk/articles/inside-the-synclavier/5607>.
