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
