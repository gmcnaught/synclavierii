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

