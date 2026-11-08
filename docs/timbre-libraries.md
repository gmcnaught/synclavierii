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
  `TOMDTA43` 12–18. Their text gives FM parameters in physical units:
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
