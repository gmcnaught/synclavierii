# Timbre libraries (M3 groundwork)

Two sources of timbres exist: the Release L timbre floppy, and a set of
later NED sample/patch libraries (user-supplied, not in the repository;
`timbres/` is git-ignored).

## Release L: `06-TIMBD/.NEWDATA` [OBS]

* 392 sectors at floppy sector 4: **8 banks of 49 sectors**. Pressing a
  bank button reads the bank's first 32 sectors (bank 0: floppy sectors
  4–35, bank 1: 53–84) plus the catalog sector.
* A bank holds fixed-size timbre records (about 0o251 words; names such as
  `WORKSPACE` inside the record, values like 1750 = 1000, 620 = 400).
  Format not decoded yet.
* Bank 0, recalled in ORK-LM: all 8 timbres play (one carrier each for
  C4).

## Later NED libraries (`Original-NED-Sample-Patch-Libraries/`)

* 92 folders, one bank each: `*NEWDATA.stmb` (raw big-endian words, 24–48
  sectors, two of 392), `NN-Entry.txt` per timbre (bank N, entry N), and
  2,075 `.caf` samples. Dated 2022 (Synclavier³-era export).
* **Mostly sampling:** 462 of 471 timbres are built from sound-file patches
  (`SynclavierPTPatchListEntry … SYNCN240`). Poly sampling is out of scope.
* **9 FM-only timbres:** `AM-DATA` 11–12 (text only, no `.stmb`) and
  `TOMDTA43` 12–18. **Correction (2026-11-09):** the `TOMDTA43` `.stmb`
  holds one valid timbre (TUNED TOMS, words 0–296, ending in TINFO + misc);
  the words after it are wave-table data, not timbre records. Entries
  12–18 ("*Unnamed Timbre*") were exported from those words, so they are
  not real timbres and the experiment below recalls garbage for timb.1–.7.
  Their text gives FM parameters in physical units:
  `SynclavierPTCarrierCoeffs` (up to 24 harmonic coefficients),
  `…CarrierPhases`, `…PIOctave` (Hz), `…FMRatioC/F`, volume and index
  envelopes (`VEnv…`, `IEnv…`: delay/attack/decay times, peak, sustain),
  vibrato, tremolo, chorus, portamento, pan.
* The `.caf` files are samples of instruments, not recordings of a
  Synclavier II's FM output, so they do not help with risk R1.

## Experiment: a `.stmb` bank in Release L

`TOMDTA43/*NEWDATA.stmb` written over bank 0 of `06-TIMBD`
(`sim.rtp --bank-file`), then `bank.0`, `timb.n`, key C4 for 0.5 s:

| Timbre | Entry text | Recall (FM writes) | C4, 1 s (FM writes) |
|---|---|---|---|
| timb.0 | "TUNED TOMS", sound-file patch | 0; screen: `Error: Missing Sound File "TOM3--43"` | 0 |
| timb.1, .2 | FM | 1,032 (four 256-point wave memories) | 0 |
| timb.3 | FM | 1,032 | 10,093 |
| timb.4 | FM | 6,352 | 12,130 |
| timb.5 | FM | 7,554 | 17,378 |
| timb.6 | FM | 5,740 | 136 |
| timb.7 | FM | 1,032 | 13,086 |

(Numbers after the `.STAB-6` fix of research log §21; the first run of
this experiment used wrong tables.)

**Inferred:** Release L reads the later bank format far enough to find
names, sound-file references and the harmonic coefficients (it computes
and loads wave memories), and four of the seven FM timbres play. Whether
it interprets every parameter as the text says is **unknown**: the format
grew after 1986, and four FM timbres stay silent. The logs from these
timbres are therefore not yet calibration data.

```bash
python3 -m sim.rtp IMAGE.simg --seconds 8 --swap-f0 06-TIMBD \
    --bank-file 'timbres/Original-NED-Sample-Patch-Libraries/TOMDTA43/*NEWDATA.stmb' \
    --buttons bank.0,timb.3 --keys 48 --hold 0.5 --fm-log out/tomdta43-t3-c4.csv
```

## Use for M3

1. Decode the timbre record: Release L's and the `.stmb` one, using the
   `.stmb` / `NN-Entry.txt` pairs as a key (same timbre, binary and text).
   That shows which fields Release L reads and why four timbres are silent.
2. Then the FM-only entries become calibration pairs: known Hz, ratios,
   coefficients and envelope times against the logged `ONU`/`NNU`/`INC`,
   wave memory, envelope and `VOL` writes.

## Original NED FM Timbre Libraries (synclavier.com, 2026-11-09)

Source: `https://www.synclavier.com/Downloads/Original-NED-FM-Timbre-Libraries.zip`,
3,337,198 bytes, SHA-256
`ef7cb2375512c3bcb2cb0c53f2f27310ebe60f45f10cb7e8f556facaeaf2b089`. No
licence file in the archive; kept in `timbres/fm-download/` (git-ignored).

### Contents [OBS]

* 17 folders, **text only** (no `.stmb`, no `.caf`): System Disk (64
  factory timbres, 1980, Denny Jaeger), Timbre Disk 1–9, Resynth Library
  1–6, Test Timbres; 943 `NN-Entry.txt` (N = bank 1–8, entry 1–8) and
  `Synclavier® II Timbres.pdf`.
* All 943 entries are FM: no sound-file patches. Same text format as the
  sample libraries (`SynclavierVirtualInstrumentTimbreVersion000`, then
  `Key partial frame count values…`; partial is the absolute 0–3 index,
  verified on 469 sample-library pairs).
* Partials per timbre: 1–4; Timbre Disks 5, 6, 8, 9 are mostly
  4-partial timbres (four FM voices per key).
* Timbre frames (`SynclavierTFPI*`, resynthesis): Resynth 1–4 nearly all
  entries, Resynth 5/6, Timbre Disk 9 (6) and Test Timbres (1) some; up to
  41 frames per partial. The System Disk and Timbre Disks 1–8 have none.
* Real-time effects (`SynclavierEM*`) in 437 entries.

### Target format [OBS: NED source, `jbemond/Software`]

SYN-5.3 reads `.NEWDATA` (any length ≥ 192 sectors; bank stride = length
/ 8, `11-TIMB:162-TMB2` `FIND.NEW.BANK`). A bank is 8 timbre records in
sequence (`03-PRIM:131-SDF2` `FIND.TIMBRE`); per timbre:

```
4 × partial: SUP (-2, 1 word)  |  46 params (prmlits p_edelay … p_new_chorus)
             then 0+ frames  (MOR -1, type, clen, …; timbre frame = 172 words)
             then optional PINFO (-3, 32 words)
optional TINFO (-4, 96 words; name = words 8–15, two chars per word, low byte first)
8 misc words
```

An empty slot is 4 × SUP + 8 misc words (12 words). Display units and
limits for each of the 46 parameters: `SYNSOU/PARMMOD/PARMSOU`
(`PAR.LIMITS`). Checked against the sample-library pairs: final decay is
stored in ms (0.019 s → 19); attack in 0.5625 ms units (0.1 s → 179,
0.573 s → 1019; limit 26667 = 15 s).

`tools/w0_image.py --newdata FILE` already installs such a file as
`W0:.NEWDATA`, so no core or HDL change is needed to load a converted
library.

### Converter: `tools/stmb.py` (2026-11-09)

```bash
python3 tools/stmb.py convert "timbres/fm-download/Original NED FM Timbre Libraries/System Disk" \
    -o timbres/fm-stmb/System-Disk.stmb --report timbres/fm-stmb/System-Disk.txt
python3 tools/w0_image.py "W0 Disk Image.simg" OUTDIR --newdata timbres/fm-stmb/System-Disk.stmb
python3 tools/stmb.py verify timbres/Original-NED-Sample-Patch-Libraries   # regression vs pairs
python3 tools/stmb.py list FILE.stmb
```

(Since 2026-11-18 the FM libraries are converted from the Synclavier V
`.synx` banks instead; see "Synclavier V banks" below. This text path
stays for AM-DATA and the sample libraries.)

Output: one 2000-sector file per folder (17 files, `timbres/fm-stmb/`,
git-ignored), each read back record by record after writing; `--report`
lists per entry what was not converted.

Encodings [OBS: `verify` on 462 sample-library pairs, plus coefficients,
tuning, ratio and vibrato on the 7 TOMDTA43 pairs exported from
non-timbre words]: times in ms; attack (volume and index) in 0.5625 ms
units; peak/sustain × 10; index peak/sustain × 1; coefficient × 10 in the
low 10 bits, phase / 5.625° in the high 6; `ptuning` = Hz × 10 with Hz =
Octave × 2^((Tran × 100 + Tune) / 1200), negative when `Track 0`; ratio
and chorus × 1000 (C + F); `decadj` = (VEnvAdj − 1) × 1000 | (IEnvAdj − 1)
× 30 << 10; vibrato rate and depth × 100, attack / 0.0035 s; `vibwave` =
wave | invert 0x10 | quantize 0x20 | raised 0x40 | stereo mode << 7
(modes per `301-SUB1`); pan centre = Pan / 1.26 (bits 2–8 of
`glidebits`), depth = TremDepth / 2 (bits 9–15); TremRate × 10 in the high
6 bits of `gliderate`; PINFO volume = 1000 × 10^(dB/20), modulator depth ×
100; misc: repeat (bit 1), arpeggiate (bit 3), repeat rate × 100, timbre
chorus × 1000; TINFO bend depth × 100, name in words 8–15. Synclavier³
omits keys equal to its defaults; the defaults used: 440 Hz, ratio 1.0,
chorus 1.0, coefficient 1 = 100 %, vibrato 5 Hz, final decay 0.1 s.

`verify` result: every field matches in all pairs except text rounding
(1–2 LSB on 6 attack/decay values), repeat/glide rates stored while
repeat/portamento is off (not in the text), and 1 of 18 partials with
`TremInvert` alone (mode 16 in the binary, mode 0 in the other 17; the
converter uses 0).

Simulator (`boot_from_w0`, VPK panel, W0 with `System-Disk.stmb`): BANK
1/2 + ENTRY recalls "Sine Wave*", "ORGAN*", "W/wind Source*",
"Port.Example" by name, no error; key 48 gives FM writes and a 521.7 Hz
estimate for the sine (C5 = 523.3 Hz; estimator resolution).

### Timbre frames (resynthesis, 2026-11-10)

169 entries (Resynth 1–6, Timbre Disk 9, Test Timbres) have frames:
`SynclavierPTCarrierCoeffs/Phases <partial> <frame>` (frame 0 = the partial
itself) and `SynclavierTFPI{Enable,SpliceTime,Volume,PitchC,PitchF,Delay}
<partial> <frame>`. Per frame the converter writes a 172-word block after
the partial's 46 parameters [OBS: `PRMLITS` 197–233]:

| Words | Content | From text |
|---|---|---|
| 0–2 | MOR (−1), type 0, length 172 | — |
| 3–7, 14–17 | interpolator, S-curve and final-decay values | 0; the RTP recomputes them on recall (`138-PRE1` `COMPUTE.ENV.PARAMS.SUB`) |
| 8 DEL, 9 ATK | delay, splice time (ms, ≤ 20000) | `Delay`, `SpliceTime` (s); no key = 1 s (5.3's new-frame default, `160-TMB0`) |
| 10 EXP, 11 RND | S-curve factor, random pitch | none; 0 (EXP is 0 in 109 of 115 stored resynthesis frames; below 100 ms splices are linear anyway) |
| 12 PK | frame peak × 10 | `Volume` (%); no key = 100 |
| 13 VOL | pre-PINFO partial volume | PINFO volume, else 1000 |
| 18 PDEL | pitch delta, cents (±4800) | `PitchC` × 100 + `PitchF` |
| 19 LOOP | loop target frame, in the frame that loops back | `PTPIFrameLoopStart/End` (10 entries; end = last frame) |
| 20–43 | 24 coefficients, phase in the high 6 bits (also for coefficient 1) | coefficients and phases; no line = `[100.0]` (a lone 100.0 is never written: 0 of 1862 lines; all-zero frames are written as `1 0.0`) |
| 44–171 | 256-byte wave table, low byte first | computed |

The wave table must be in the file: at splice time the RTP copies these 128
words to wave memory (`303-SUB3`, `352-SPLC`); it computes them only when a
frame is edited (`131-SDF2` `COMPUTE.TIMBRE.FRAME`). The converter uses 5.3's
`COMPUTE.WAVE` (`198-SYN2`) with the RTP sine table, which is exactly
floor(1024 + 1023.5 · sin(2πi/256)) [OBS: all 256 points of `.STAB-7` in the
W0 image]. No (bank, text) pair with timbre frames exists: every frame block
in the 92 sample-library banks and the 8 jbemond W0 demo banks is type 1
(48-word patch list). 767 type-0 blocks (115 distinct) survive in slack space
after the live records; their tables come from mixed tools: the
resynthesis program's `calcwave` (`RSYNCAT/21-CALCW`) reproduces 28 exactly
and 30 within 2 LSB, `COMPUTE.WAVE` 8 exactly; the rest were edited or
analysed with more than 24 coefficients.

### Real-time effects (2026-11-10)

TINFO words 16–55 (`TI.RTE`) are 8 expression inputs × 5 words [OBS:
`139-PRE2` PARSUB, `RB.LOOK`]: slots 0 velocity, 1 pressure, 2 pedal 1,
3 pedal 2, 4 mod wheel, 5 ribbon, 6 kbd CV, 7 breath; per slot the partial
bits (low 4 normal, next 4 inverted), sampled destination bits, continuous
destination bits, and the same two for inverted sensing. Bit meanings:
`TIMLITS` `N.*` (sampled: VE.ATK, VE.IDEC, VE.DEL, HE.ATK, HE.IDEC, VE.FDEC,
HE.DEL, P.RATE, HE.FDEC, VIB.ATK, DYN.ENV; continuous: V.RATE, V.DEPTH,
VE.PKSUS, V.MDEPTH, S.RATE, HE.PK, HE.SUS, S.DEP, S.PAN, TUNING, FMRATIO,
REPRATE, CHORUS, TVOL).

Text: `SynclavierEMDestinationFactors 0 <source> <n> <factor per destination
index>` (1 normal, −1 inverted) and `SynclavierEMScaleFactors 0 <source> <n>
<factor per partial>`. Pinned on the 462 pairs:

| Text | NED |
|---|---|
| source 1 / 2 / 3 | mod wheel / velocity / pressure slot |
| source 6 | keyboard envelope: no RTE bits, carried by the PINFO `KBD*` keys |
| source 7, destination 0 | velocity slot, DYN.ENV |
| destination 0 / 3 / 10 | VE.PKSUS (volume) / TUNING / VE.ATK |
| destinations 23, 26 | V.DEPTH and S.DEP (always together in the pairs; 23 = V.DEPTH is inferred: the usual pressure / mod wheel patch) |
| ScaleFactors | slot partial bits; omitted when every existing partial is affected; missing trailing partials count as 1 |

`verify`: RTE slots 1–7 match in 462/462 pairs, slot 0 in 459 (3
`FLTDTA43` entries have DYN.ENV in the binary but no source-7 line in the
text). The FM libraries also use destinations 1, 2, 5, 11, 12, 16–20, 22, 28
(velocity → 2, 11, 12, 16–20 most often), which no pair contains, and the
panel button table that would give Synclavier³'s order (`*.L` LPN literals)
is not in the published source. They are left out and listed in the
reports: 246 of 437 entries convert completely. One Synclavier³ text export
of a timbre with known RTE patches would pin the rest.

Not converted (listed in the reports):

| Item | Entries | Status |
|---|---|---|
| Real-time effects: destination indices other than 0, 3, 10, 23, 26 | 191 of 437 entries (367 of 654 source→destination uses) | not pinned by any pair; left out and listed per entry (see "Real-time effects") |
| Timbre frames: EXP, RND (no text keys) | 169 entries | written as 0 (see "Timbre frames" below) |
| Portamento rate without a `PortRate` key | 6 of 75 | 700 assumed (others: gliderate = ⌈√(1000 · round(10 / PortRate))⌉; `301-SUB1` COMPUTE.GLIDE steps by rate² / 1000 and the text is 10 / step, exact on the 4 real pair partials) |
| Polyphony (`TBPIPolyphony`) | 236 | not the NED field: NED keeps the voice limit in misc word 0 bits 8–15 (`182-UPD2`; 0 = all voices). In the pairs, `Polyphony 2` occurs with limits 0, 4 and 128, and limits 1, 4, 90, 128 occur without the key, so the text does not carry it; written as 0 |
| Pedal/keyboard stereo modes (1–4) | ? | no distinct text; not recoverable |
| PINFO dynamic envelope (`pi_denvl/h`), TINFO velocity words 56–57 | — | not in the text; written as 0 |

### Synclavier V banks (`.synx`, 2026-11-18): the conversion source

Source: `timbres/Synclavier II Timbres/` (git-ignored), 17
`Synclavier_Bank_*.synx` (Arturia, dated 2016-05-31): the same 17 libraries
as the Regen text export, 941 presets, every one paired by name with an
`NN-Entry.txt` (Test Timbres' "1111 - Sine Wave" has no text entry). The
FM libraries are now converted from these, so the core's timbres and the
Synclavier V reference (`tuning-references.md`) start from the same data.
**TOMDTA43 is not in the pack** (it is a sample library); no frame holds
any of TOMDTA43 entries 12–18's 28 coefficient sets.

```bash
python3 tools/synx.py convert "timbres/Synclavier II Timbres/Synclavier_Bank_System Disk Timbres.synx" \
    -o timbres/fm-synx/System-Disk.stmb --report timbres/fm-synx/System-Disk.txt \
    --regen "timbres/fm-download/Original NED FM Timbre Libraries/System Disk"
python3 tools/timbre_disk.py out/images/W1-SYNX.IMG timbres/fm-synx/*.stmb     # 17 libraries, 17 MB
python3 tools/synx.py verify BANK.synx TEXT_DIR      # harmonic/frame blocks vs the Regen text
python3 tools/synx.py dump BANK.synx NAME            # frames of one preset
```

`convert` decodes each preset into the Regen text keys and encodes it with
`stmb.encode_entry`, so the NED encoding is shared with the text path.
Bank/entry come from the preset number (`LLBE - name`); the Regen export
orders some libraries differently (System Disk: synx 1212 Church Bell,
Regen 12 Galactic Cymbal).

#### Format [OBS]

A stored zip of presets `<library>/<NNNN> - <name>`; a preset is a Boost
text archive (`serialization::archive 10`): length-prefixed parameter
names with normalised values (0–1), then binary blocks
`<len> <name> <size> <bytes>`. `Partial P Frame F` (P 1–12, F 0–50) = 112
float32 LE:

| Floats | Content | Mapping (NED text → float) |
|---|---|---|
| 0 | frame enable | 1 / 0 |
| 1, 2 | delay, splice time (`TFPIDelay`, `TFPISpliceTime`) | time taper (below) |
| 4 | pitch coarse (`TFPIPitchC`) | 0.5 + semitones / 96 (±48; beyond: stored 0) |
| 5 | pitch fine (`TFPIPitchF`) | 0.5 + cents / 250 |
| 6 | frame volume (`TFPIVolume`) | percent taper |
| 8 | 1 on the loop-end frame | `PTPIFrameLoopEnd` |
| 10 | loop start / 50 (on the loop-end frame) | `PTPIFrameLoopStart` |
| 3, 7 / 9, 11–15 | constant 1 / 0 | unknown |
| 16–39 | carrier harmonics 1–24 | percent taper |
| 40–63 | carrier phases 1–24 | (0°, 0), (34, 0.136), (144, 0.356), (180, 0.5), (216, 0.644), (326, 0.864), (360, 1); 64 steps of 5.625° |
| 64–111 | modulator harmonics and phases (Synclavier V only) | in all 13,310 enabled frames: harmonic 1 = 1, rest 0, phases 0 (NED's sine modulator) |

Frame 0 is the partial's own harmonic set. Partials 5–12 are never used; a
partial is in use when its Partial Volume is not "Off".

Parameters (`/Library/Arturia/Synclavier V/resources/Synclavier V.xml`):
item lists store item index / (N − 1) and name their values (e.g.
`Sync125_0CentsList`, 2501 items, −125.0…+125.0 cents; `Sync9OctaveList`
6.875 Hz × 2^i; `SyncVolume50DBList` Off, −49.9…0.0 dB;
`Sync100PercentList` and `Sync360DegreesList` non-uniform, generated in
`synx.py`). `SynclavierTable(...)` tapers are compiled into the plugin;
their breakpoints, fitted to the pairs (residuals ≤ 0.5 % of values, all
explained below):

| Table | Used for | Breakpoints (value, normalised) |
|---|---|---|
| Sync30_000 | envelope times, vibrato attack, portamento rate, frame delay/splice | (0 s, 0), (0.05, 0.2), (0.1, 0.3), (0.2, 0.38), (0.5, 0.5), (1, 0.6), (2, 0.68), (4, 0.76), (10, 0.88), (15, 0.92), (30, 1) |
| Sync100_0 | volume peak/sustain (%), harmonics, frame volume; index peak/sustain (0–1000) at × 10 | (0, 0), (8, 0.32), (20, 0.56), (50, 0.8), (100, 1); 19.6 / 19.7 % stored 0.5403 / 0.5423 |
| Sync50Herz | vibrato, tremolo, repeat rate | (0 Hz, 0), (5, 0.4), (10, 0.6), (20, 0.76), (50, 1) |
| Sync25_000Semitones | vibrato depths, pitch bend depth | (0, 0), (1, 0.4), (5, 0.72), (20, 0.96), (25, 1) |
| SyncDecayAdjust | volume decay adjust | 1 + x / 0.8 |

#### What the `.synx` does not carry [OBS]

* **Real-time effects:** all 941 presets hold the same 5 modulation slots
  (pitch bend → tuning, sustain pedal → note sustain, velocity → volume,
  mod wheel → vibrato depth). The Regen text has RTE lines in 417 entries
  (`--regen` adds them).
* **Index envelope adjust** (`IEnvAdj`; "Harmonic Adjust" is commented out
  in the XML): 178 partials in 79 entries (`--regen` adds them).
* Negative FM ratios (Synclavier V: 0–16): 31 partials. Pitch bend depth:
  12 entries hold the 2-semitone default where the text has another value.
* Names: the file name, without `/ # *` (`W/wind Source*` → `Wwind Source`).

#### Real-time effects and index adjust from the Regen text (`--regen`)

`--regen TEXT_DIR` adds, per preset, the matching Regen entry's
`SynclavierEM*` lines and `IEnvAdj` values (partials in use only). Match:
same name, then fewest harmonic/frame differences, then the same bank/entry
number. 4 presets have same-name Regen entries with different RTE data
(Timbre Disk 3 "Trumpet" 16/18, Resynth 4 "Tympani" 88/71/72, Timbre Disk 8
"BASS ORGAN WEATH" 41/51); the report names them. Encoding is
`stmb.encode_rte`: only SYN-5.3 TINFO RTE bits are written; Regen
sources/destinations with no pinned NED bit are dropped and listed (367
uses, as in the text path). With `--regen`, all 40 RTE words and the
decay-adjust word equal the text path's in all 941 presets.

Could Regen carry effects the timbres never had? [OBS] In the 462
sample-library pairs (NED binary + Regen text) RTE slots 1–7 agree in all
462 and slot 0 in 459; the 3 others have a dynamic-envelope bit in the
binary and none in the text. The one FM timbre with a NED binary (System
Disk "W/wind Source*", Synclavier³ demo bank) has a velocity routing
(slot 0, partial 1, sampled bit 7) and no EM line in the text. Both point
to Regen dropping routings, none to it adding them. The velocity → volume
line is not an exporter default: 52 of 64 Resynth 1 entries, 1 of 64 in
Timbre Disk 8, 0 in Test Timbres. [UNKNOWN] Without NED binaries of the FM
libraries, an added routing cannot be excluded. Velocity and pressure
routings need the velocity/pressure keyboard (VPK, which the core
emulates for SYN-5.3); a 1980 Synclavier II with the original keyboard has
no such inputs.

#### How Synclavier V stores NED data [OBS]

* FM off: `Partial Modulation` (F.M. amount) 0, the index envelope at its
  reset values (peak and sustain 1000, attack 3 ms, final decay 0.1 s) in
  all 398 partials whose Regen text has no index peak or sustain. NED has
  peak and sustain 0 there. `convert` writes index peak and sustain 0 and
  clears a final decay of 0.1 s (attack 3 ms is the FM export's default
  and is kept). Inaudible either way.
* Rates of features that are off hold reset values (tremolo 5 Hz in 1,803
  partials, repeat 5 Hz, portamento 0.225); `convert` writes them only
  while tremolo depth, repeat/arpeggiate or portamento is on, as the text
  does.

#### Cross-check against the Regen path

All 941 presets encoded both ways (`synx.py convert` and `stmb.py
convert`) and compared word by word, real-time-effect words excluded:
276,632 words in 140 field positions (partial parameters, frame words 0–43,
PINFO, TINFO, misc), 1,907 differ, in 39 positions; 101 positions agree in
every preset. The differences:

| Field | Partials | Cause |
|---|---|---|
| glide bits / rate | 136 / 369 | 33 presets have portamento on in the `.synx` with their own rates, off in the text (the text writes `PortOnOff` only as 1); sources disagree, `.synx` kept |
| decay adjust (index part) | 178 | `IEnvAdj` not in the `.synx`; equal with `--regen` |
| PINFO / frame volume | 47 / 149 | 0.1 dB steps in the `.synx` (231 vs 232) |
| FM ratio | 31 | negative ratios |
| timbre name | ~190 | punctuation |
| pitch bend depth | 12 | lost in the `.synx` |
| frame count | 11 | the `.synx` has one frame after the loop end (splice 0, the loop-end frame's harmonics, lower volume); not in the text; kept |
| partial present | 14 | text partials with default content only; Volume Off in the `.synx` (silent either way) |
| Tympani entries, 6 others | < 25 each | several presets named "Tympani" (name pairing ambiguous); single-value disagreements |
| frame pitch, splice | 21 / 5 | pitch beyond ±48 semitones stored 0, +5 stored 3.875, 0.1 s splice stored 0 |

Regen's omitted-key defaults (`stmb.EXPORT_DEFAULTS`, ported from branch
`claude/kind-rubin-r57h8c`): the text header's fifth number is 927 in all
471 sample-library entries and 3999 in all 943 FM-library entries, and the
two exports omit different defaults [OBS unless marked]:

| Key omitted | 927 (sample libraries) | 3999 (FM libraries) | Evidence |
|---|---|---|---|
| `VEnvPeak` | 0 | 0 | 100.0 written 2,132 times, 0.0 never; Synclavier V holds 0 in 236 of 253 partials without the key (e.g. Resynth 1 "Strings #1": attack 1.25 s to peak 0, initial decay 7.8 s up to sustain 100). `stmb.py` used 100 before |
| `VEnvAttack` | 3 ms | 3 ms | never written while 0, 1, 2, 4, 5 ms are; the 927 binary holds 5 (2.8 ms) |
| `IEnvAttack` | 0 | 3 ms [INF] | 927 binaries hold 0 (639 partials); 3999 writes 0.0 1,058 times and never 3 ms; Synclavier V holds 3 ms |
| `TremSync` | off | on | 927 writes only "1", 3999 only "0" (359); Synclavier V has sync on in the 183 partials without the line |

`stmb.py verify` with these: eattack 657/657 (was 656), the rest
unchanged. `synx.py` entries are marked export 3999 (keys it omits follow
the FM export).

## Library disk: all libraries on W1: (2026-11-10)

`W0:.NEWDATA` holds one library: 8 banks of 8 timbres. That is a limit of
one `.NEWDATA` file, not of SYN-5.3 [OBS]:

* the panel's BANK/ENTRY recall looks for `.NEWDATA` in the **current
  catalog** first, then in the system catalog (W0:)
  (`SYNRSOU/11-TIMB/162-TMB2` `FIND.NEW.BANK`, `SEARCH(NEWDATA, TRUE,
  ACTIVE.LEVEL)` then level 0);
* the Timbre Directory (A) reads `.NEWDATA` from the current catalog or
  any device (`SYNSOU/DIRMOD/570-DIRS` `COMPUTE.AVAILABLE.DEVICES`,
  `575-TIMB`).

So, as with NED's timbre floppies, each library can sit in its own
sub-catalog on a separate W1: image, and W0: never has to be rebuilt to
add timbres:

```bash
python3 tools/stmb.py convert "timbres/fm-download/.../Timbre Disk 3" -o timbres/fm-stmb/Timbre-Disk-3.stmb
python3 tools/timbre_disk.py W1-TIMBRES.IMG timbres/fm-stmb/*.stmb        # 17 libraries: 17 MB
python3 tools/w0_image.py "W0 Disk Image.simg" OUT --w1                   # a state image with W1:
```

Sub-catalog names: SYSDISK, TIMBDSK1–9, RESYNTH1–6, TESTTIMB (or
`NAME=FILE.stmb`). In SYN-5.3: D (Subcatalog Directory), type
`W1:TIMBDSK3`, RETURN; the Main Menu shows "Current Catalog: W1:TIMBDSK3"
and BANK/ENTRY recall that library; the Timbre Directory (A) also lists
the current catalog first among its devices (`570-DIRS:42-48`), showing
the library's 8 banks by name (seen on the MiSTer); entering `W0:` again
returns to W0:.NEWDATA.

Verified: simulator, W1:TIMBDSK3 entered, BANK 1 ENTRY 2 → "PIPE ORGAN
#1" (Timbre Disk 3; without entering: W0's "SIMPLE FM SINE"); MiSTer
(.62, `W0-53-W1.SST`, image in S4): same, the note plays, 0 underruns.
`tests/test_timbre_disk.py`.

The same disk can carry sequences: `tools/timbre_disk.py --seq
DEMOS:N=FILE.sseq` adds a sub-catalog of `.SQnDATA` files, which SEQUENCE
+ button N recalls once it is the current catalog
([`sequences.md`](sequences.md)).

## Original NED Sample/Patch Libraries on W1: (analysis, 2026-11-11)

Source: `https://www.synclavier.com/Downloads/Original-NED-Sample-Patch-Libraries.zip`,
586,070,014 bytes (the server's content-length on 2026-11-11 equals the
local `timbres/Original-NED-Sample-Patch-Libraries.zip`). Git-ignored.

### Contents [OBS]

* 92 folders. 90 hold a `*NEWDATA.stmb`: 77 one bank, 10 two banks,
  DRMDTA40 three, PNODTA71 and PRCDTA01 eight: **116 banks, 464 timbres**.
  AM-DATA: 2 FM entries, text only (`stmb.py convert`). NED_TL23: all
  2,075 `.caf` sound files, no timbres.
* A timbre names its sound files in type-1 frames (48 words): words 3–6 =
  the 8-character name, low byte first. **No catalog path.**
* 774 distinct sound files are referenced (all present): 453,808 sectors,
  232 MB. 1,301 are referenced by no timbre: 496 MB. All 2,075: 1,421,757
  sectors, 728 MB; 63 instrument prefixes (most files: CLT 159, PNO 127,
  BCL 111; 18 prefixes such as CLT, BCL, TBA, VOX have no timbre at all).
* Timbre names end in their poly-memory size in MB (`FULL PIANO   5.7`);
  the largest is about 10 MB.

### A `.caf` is a NED sound file [OBS: all 2,075 files]

* Chunk `SNCL`, 1,536 bytes = sectors 0–2 of the NED sound file (header
  and symbol table, [`poly-synth.md`](poly-synth.md) §5), big-endian words.
  Valid data (words 2–4) = CAF frames × channels in 2,075 of 2,075; the file
  handle (word 53, high byte first) is the file name.
* Chunk `data`: 4-byte edit count, then 16-bit little-endian PCM; 78 stereo
  files are interleaved L/R as NED stores them. Rates: 50 kHz 1,959, 100 kHz
  63, 65/40/45/25/30 kHz the rest. 922 headers have sample-rate word 42 = 0
  and give the rate as period index (word 21), which the loader accepts.
  Compat 4 in 2,051, 1–3 in 24.
* Sample rates checked (2026-11-18): in all 2,075 files the header's
  `data.end` time (words 9–11) × rate × channels = valid data (words 2–4),
  so NED's own rate is the header's. The 62 stereo files at 100 kHz
  (`*-50`: BDR, SNR, TOM… drums) and SYNDN260 (mono) are 100 kHz per
  channel: NED keeps the rate per channel (CLARA4, stereo: rate 500, twice
  CLARA3's data), and SYN-5.3 doubles the address step for stereo
  (`301-SUB1:197-199`), so they play 100,000 frames/s. None of the 63 is
  used by a timbre (they reach W1: only with `--all-sounds`). The rate in
  the text's `SynclavierPTPatchListEntry` lines (the number before the
  file name) is Synclavier³'s, not NED's: the type-1 frame holds no rate,
  and the text says 50000 for 14 patches on 40 kHz files (FLTDTA42) and 1
  on a 25 kHz file (HRPDTA43 11, HRPCN543). The converted files keep the
  header, so SYN-5.3 uses the real rate. Not yet checked by playing one of
  these in the simulator (needs the W0 image).
* Conversion is a copy: `SNCL` words + samples byte-swapped to big-endian,
  padded to 3 + total-data sectors (word 7). No resampling. Loops, pitch,
  marks and the caption stay as they are. (`sound_import.py` builds headers
  from WAV/AIFF and is not needed here.)

### How SYN-5.3 finds a patch's sound file [OBS]

`198-SYN2:430-500`, recall of a timbre whose file is not in poly memory:
interpreter asset library (only when `interp_is_running`) → floppy cache →
**`FIND.SOUND`** (sound-file cache) → `LOCATE` on the active level / current
catalog / system catalog, only when there is no cache → optical index.

The cache (`197-PAL2` `SETUP.CACHE`, `TRAVERSE.DEVICE`) holds every sound
file on W0: and then W1:, recursing into type 6/7 sub-catalogs to depth
10, 8 words per file in poly memory; `FIND.SOUND` takes the first name
match. It is built when `interp_real_time_prefs(SYNCLAVIER_PREF_CREATE_CACHE)`
returns the bit. On this hardware the natives return their argument (as for
the D70 poll, [`devices/d70-midi-subsystem.md`](devices/d70-midi-subsystem.md))
[INF], so the cache exists and **sound files can sit in any W1: sub-catalog**.
A W0: file with the same name would shadow a W1: file. Not yet checked: no
test has recalled a sound file from W1: in SYN-5.3 (the M17 open item).

### Limits

| Limit | Where [OBS] | Value | Library needs |
|---|---|---|---|
| SCSI disk size | was: `hdl/core/sd_floppy.sv` clamped W0/W1 at 65,536 blocks with 16-bit block addresses (`sd_floppy.sv`, `dev_scsi.sv`); our choice, sized for the W0 images. READ(10) carries a 32-bit LBA; NED sizes a disk from READ CAPACITY up to 24 bits of sectors (`XPL/DEVUTIL` Find_Win_Size) | now 2^24 blocks (8 GB) | — |
| Catalog entry size | `tools/ned_disk.py` `add_file` writes 16-bit start and length; NED packs MS start (bits 8–15) and MS length (bits 4–7) into the type word (`XPL/CATCODE:58-64,328-333`) | 32 MB per catalog in the tool; 24-bit start, 20-bit length in NED | MS bits in `walk` and `add_file` |
| Catalog entries | root and type 7: 128; type 6: 32 | — | PNO 127 files; CLT 159 needs two sub-catalogs |
| Sound file length | `197-PAL1:378-386` | < 65,536 sectors | largest 2,895 |
| Poly memory | M10 | 224 MB | largest timbre ≈ 10 MB |

### Options, by period capacity

The Synclavier 3200/9600 shipped with hard disks such as 80 MB or 320 MB,
or optical WORM drives up to 2 GB.

| Option | Contents | Size | Needs |
|---|---|---|---|
| **A: W1: 320 MB class** | 116 banks repacked into 8-bank `.NEWDATA` libraries by instrument family (about 15–18), the 774 referenced sound files, and the existing 17 FM libraries + DEMOS | ≈ 250 MB | HDL disk width, `ned_disk` MS bits, CAF copy, bank repack |
| B: W1: 1 GB | A + the 1,301 unreferenced sound files (B screen / patch building) | ≈ 745 MB | as A |
| C: optical | full library as an optical volume (period-correct for the whole set) | 728 MB+ | optical target (spike S1, not modelled) |

### Implementation (option A, 2026-11-11)

| Part | Change |
|---|---|
| HDL | `sd_floppy.sv` word port `{drive, block[23:0], word}`, W0/W1 up to 2^24 blocks (8 GB, clamped there); `dev_scsi.sv` 24-bit LBA, READ CAPACITY of the image size, MODE SENSE block count 3 bytes (FFFFFF at 2^24, also in `sim/devices/scsi.py`); `synclavier_core.sv` packs the four word-port users into the new address |
| `tools/ned_disk.py` | catalog entries with start bits 16–23 and length bits 16–19 in the type word (`entry_fields`, `entry_words`); `add_file` reads only catalog sectors (`DiskWords`), so a 274 MB image builds in 5 s |
| `tools/stmb.py` | `bank_bytes()`: up to 8 parsed banks → `.NEWDATA` bytes |
| `tools/sample_library.py` | `.caf` → NED sound file (`SNCL` + samples, checked against the header); banks grouped by family (`FAMILIES`), 8 to a library, a bank file kept whole; TOMDTA43 entries 2–8 (wave-table words, not timbres) left empty; AM-DATA's two FM entries encoded from text |
| `tools/timbre_disk.py` | `--samples DIR [--all-sounds]`: one sub-catalog per library (type 7 above 31 files) holding its `.NEWDATA` and every sound file its timbres use; a sound used by two libraries is in both (161 copies, 31 MB) so each library is complete |

Libraries (`python3 tools/sample_library.py DIR` lists every bank):

| Sub-catalog | Banks (bank files) | Sound files |
|---|---|---|
| PIANO1 | HPCDTA40, PNODTA40 ×2, PNODTA41, PNODTA42 | 43 |
| PIANO2 | PNODTA71 ×8 (Concert Grand) | 84 |
| BRASS1 | FHNDTA40, FHNDTA41, FLGDTA40, TBNDTA40 ×2, TBNDTA41, TPTDTA40, TPTDTA41 | 72 |
| BRASS2 | TPTDTA42, 44, 46, 47, 49 | 74 |
| WINDS1 | FLTDTA40 ×2, FLTDTA41–43, MWWDTA40–42 | 39 |
| WINDS2 | MWWDTA43, SSXDTA40, TSXDTA40 | 29 |
| STRINGS1 | ABSDTA40, ABSDTA42, BJODTA40, EBSDTA40, GTRDTA40, HRPDTA40 ×2 | 61 |
| STRINGS2 | HRPDTA41 ×2, HRPDTA42 ×2, HRPDTA43, VLNDTA40 ×2 | 47 |
| STRINGS3 | VLNDTA41 ×2, VLNDTA42 | 26 |
| DRUMS1 | BDRDTA40, CRADTA40, DRMDTA40 ×3, GNGDTA40, HIHDTA40, RIDDTA40 | 115 |
| DRUMS2 | SNRDTA40, SPLDTA40, TMPDTA40, TOMDTA40, 42, 43 | 44 |
| PERC1 | CBADTA01, CBLDTA01 ×2, CGADTA01, CLVDTA01, GUIDTA01, GUIDTA02, MBLDTA01 | 51 |
| PERC2 | MBLDTA03, MPCDTA01–04 | 16 |
| PERC3 | PRCDTA01 ×8 (Latin percussion) | 106 |
| PERC4 | RATDTA01, SHKDTA01 ×2, TAMDTA01, TMBDTA01, TRIDTA01, WBKDTA01, XTKDTA40 | 47 |
| MALLETS | CHIDTA40, KBADTA40, MBADTA40, OBLDTA40, STDDTA40 | 30 |
| SYNTH1 | AM-DATA, SYNDTA40–46 | 24 |
| SYNTH2 | SYNDTA47–53 | 27 |

Build (with the FM libraries and the demo sequences):

```bash
python3 tools/timbre_disk.py W1-SAMPLES.IMG timbres/fm-stmb/*.stmb \
    --samples timbres/Original-NED-Sample-Patch-Libraries \
    --seq DEMOS:0=SQ0.sseq ... --seq DEMOS:4=SQ4.sseq       # 274 MB
```

In SYN-5.3: D (Subcatalog Directory), `W1:PIANO2`, RETURN; then BANK n,
ENTRY m. The W0: image has no sound file of the same name as a library
file (W0: holds CLARA3 and CLARA4 only).

Verified:

* Read-back: all 935 sound files and 18 `.NEWDATA` files in the image are
  byte-identical to their sources; 894 files start above sector 65,535.
* Simulator (SYN-5.3, VPK, `W0-53.IMG` + the 274 MB W1:): `W1:PIANO1`
  entered, BANK 2 ENTRY 1: the panel shows `LOADING SOUND FILE "PNOGN340"`,
  then `FULL PIANO   5.7`; all 14 sound files of that timbre are in poly
  memory; no terminal error. `W1:SYNTH2` (the last library, about 270 MB
  in), BANK 5 ENTRY 1: `SYN51 PAD   1.93`, its 6 sound files in poly memory.
* Board lockstep (HDL = Python), SYN-5.3 boot with this W1: (`w0boot --poly
  --vpk --fm-voices 8 --w1`, state image `w0_image.py --w1 --disk-us 0
  --seek-us 0 --fm-voices 8`): 19,600,000 instructions, 736 SD reads,
  identical. The boot's sound-file cache build reads 74 W1: blocks, 18 of
  them above 65,535 (up to 560,350).
* MiSTer .62 (RBF of PR #65, worst setup slack +0.243 ns; `W0-53.IMG` in
  S3, `W1-SAMPLES.IMG` in S4, `W0-53-W1-VT640.SST`): boot to the Main Menu;
  D, `W1:PIANO1`: "Current Catalog: W1:PIANO1"; BANK 2 ENTRY 1 (panel
  buttons over MIDI channel 16): "Current Timbre: FULL PIANO 5.7", all 14
  sound files found in DDR3 poly memory (`/dev/mem`); `W1:SYNTH2` BANK 5
  ENTRY 1: "SYN51 PAD 1.93", its 6 sound files in poly memory. Not yet
  listened to.

### Patch transpositions an octave off (2026-11-17)

The sample libraries are Synclavier Regen exports (the patch `.stmb`
binaries, the `NN-Entry.txt` texts and the `.caf` sound files). In whole
families the recorded pitch is an octave below the patch's transposition
key, so on the core (and in the simulator, which the HDL matches) FULL
PIANO played A4 at 220 Hz and C4 at 130.8 Hz.

* How SYN-5.3 pitches a patch entry [OBS]: the type-1 frame's `PT.TRA`
  (word 10, low byte = key, middle C = 36; `SYNLITS/PRMLITS:271-276`) is
  the key that plays the file at its own rate: `303-SUB3` MRLCH = 2816 +
  1024 − `COMPUTE.PATCH.XPOS(PT.TRA)` + TOFFS − SRATE, and
  `COMPUTE.PATCH.XPOS` is `COMPUTE.KBD.PITCH`'s formula (`190-NEW0`), so
  FREQ.NUM there is 3840: 50 kHz at the recorded pitch. The simulator
  does exactly that (key A4 in FULL PIANO's PNOA#340 entry, PT.TRA A#4:
  the file one semitone down, 220 Hz = its A#3 recording).
* The rates are not the cause: in every header data.end × rate ×
  channels = the valid data (all 2,075 files; FULL PIANO's 14 at 50 kHz),
  and the Regen text's patch-list rate is not used by the conversion.
* Regen's text and binary agree (`PNODTA40/22-Entry.txt` PNOA#540: keys
  90-96, transpose 94 = MIDI A#6; binary PT.TRA 70 = 94 − 24). Its
  transposition keys follow the file names read with NED's octave numbers
  (C3 = middle C); TPT, SSX, TSX, most FLT were recorded that way, but PNO
  (both pianos), VLN, HRP, FHN, TBN, FLG, GTR, EBS, ABS, HPC and SYN41-51
  were recorded an octave lower (their names read with standard octaves).
* Second witness: Arturia ships PNOA#540 unchanged (`Synclavier
  V/Factory/Piano - loud.wav`, identical samples) and gives it root key
  A#5 (preset "Random Grains 2", `Partial File MIDI Key 5` = 82): the
  recorded pitch, not Regen's A#6.

Correction (`tools/sample_pitch.py`, applied by `sample_library.py` and
`timbre_disk.py --samples`; `--no-pitch-fix` keeps the exports' keys):
`sample_pitch.py scan` measures each patch-list file's fundamental
(16384-point spectrum, subharmonic summation over 8 harmonics) into
`data/sample-pitch.tsv`. A file's key is its measurement when the octave
is clear (margin ≥ 0.15) and the pitch class is the name's note; low notes
with a weak fundamental take their name group's relation (e.g. PNO?40:
12 of 12 recorded at their name with standard octaves). A patch entry
moves by exactly ±12 only when that key is an octave from PT.TRA and
matches the name's note; everything else is left as exported.

Result (2026-11-17): 1,735 of 3,646 patch entries, 306 sound files
moved up an octave in pitch (PT.TRA −12), 3 down (4 entries on CHI chimes,
inharmonic, least certain; 2 on FLTDTA42 flutes). W1-SAMPLES built with
and without the correction differs in exactly 1,735 words, all PT.TRA
words in the library `.NEWDATA` files; built without it, it is identical
to the image on the .62. Simulator, FULL PIANO from the corrected W1:
A4, C4 and A5 sound at their pitch (the octave below at −40 dB or less);
A2's fundamental is 16 dB under its second harmonic, as low piano notes
are, with nothing at 55 Hz. Not yet played on the .62.
