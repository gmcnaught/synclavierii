# Release L disk image (June 1986)

**Source:** GitHub [`Synclavier/Synclavier_Distributions`](https://github.com/Synclavier/Synclavier_Distributions),
`Release_L/NED_Synclavier_Release_L_DD_Floppies.simg`. Commit and checksum
are in [`sources.md`](sources.md). That repository has **no licence file**, so
no binaries from it are copied here; use [`tools/ned_disk.py`](../tools/README.md)
to list and extract them yourself.

## 1. What's in it

One 5 MB NED-format image holding **19 double-density floppies** (404
sectors each) for "Release L for ORK" (the original keyboard). Each floppy is
a type-7 sub-catalog with its catalog in its first sectors and files from
sector +4.

| Floppy | Purpose | Notable files |
|---|---|---|
| 01-BOOTD, 02-BOOTF, 03-SYSTD | Boot / system disks | **`.LD-6`** (high-memory loader, 1535 words), **`MONITOR`** (OS, 21 834 words), `.ED-6` (editor), `CONFIGUR` |
| 04-SCRPT | Script demos | SCRIPT sequences (text) |
| 05-SEQD, 06-TIMBD | Sequence / timbre storage | data |
| 07-AUDIO | Audio diagnostics | its own `MONITOR` |
| 08–13 INST1–6 | Winchester install set | `FORMCOPY`, `SHUFFLE`, `.SYSTEM` (spans 6 disks) |
| 14–17 RTPO1–4 | Real-time program | `ORK-LM`, `ORK-LFM` (spans 4 disks) |
| 18-UTILS | Utilities | `FIND`, `LISTING`, `RECOVER`, `TAPECAT`, … |
| 19-DIAGS | Diagnostics | `FLOPTEST`, `KEYBOARD`, `M128TEST`, `MEGTEST`, `MEMBURN`, `MIDI`, `MULTICHN`, `POLYTRON`, `PRINTEST`, `PSTEST`, `TAPETEST` |

The diagnostics cover peripherals and memory. **There is no CPU test.**

## 2. Catalog format

Worked out here, consistent with `hansliss/syncextract`.

* Sector = 256 words = 512 bytes. Words are **big-endian** in the image file.
* Catalog entry = 8 words: `name[4]` (8 characters, *low byte first* in each
  word), `start` (sector, **relative to the catalog's base**), `length`
  (sectors), `words` (file length in words, low 16 bits), `type`.
* Types seen: 0 text, 1 executable, 3/4 data, 6 sub-catalog (4-sector
  catalog), 7 floppy-sized sub-catalog (1-sector catalog), 8 large
  executable (multi-disk).
* An empty name is free space; an all-zero entry ends the catalog.

## 3. Findings

### 3.1 `.LD-6` is three position-independent 512-word loaders

| Offset (octal) | Loader | Devices used | Entry vector |
|---|---|---|---|
| 0 | floppy | D100–D104 | `IM(16) TO RTRA`, … (five relative jumps) |
| 1000 | IMI Winchester | D105–D107 | five relative jumps |
| 2000 | SCSI | D24–D27 | four jumps; entry 4 is `IM(7) TO D50` in a loop (ring the bell forever: ext-memory copy not supported) |

The floppy loader matches NED's FLPLOAD source instruction for instruction:
* every entry disables interrupts with `IM(-20) TO D1`
* the overlay entry is `R2 TO R6`, `IM(1) TO R16` (RFIRST), `RE(RDCAT) TO RTRA`
* the boot entry loads the packed name `"MONITOR"` into R0–R3

That's a second independent check of the disassembler on a real binary.

All three boot and system disks carry an identical `.LD-6`.

**Boot implication:** the loader is position-independent and has one slot per
boot medium. So the boot ROM (on the MFC/D40Q card, **not in this image**)
loads `.LD-x` and starts the slot for the boot device. The later `.LD-7`
uses 768-word slots (MRGLOAD). See [`boot-and-loaders.md`](boot-and-loaders.md).

### 3.2 Release L code is compiled for Model B

| Binary | Words | `TO MR15I` (Model A/B push) | `TO MR12D` (Model C push) |
|---|---:|---:|---:|
| `MONITOR` | 21 834 | 124 | 0 |
| `ORK-LM` (part 1) | 36 096 | 155 | 0 |
| `.LD-6` | 1 535 | 0 | 0 (no stack use) |

Release L (1986, original keyboard) targets the **Model B** CPU (D1 + D300).
For our boards that is still useful. The XPL manual says Model C-compiled
modules can't be used by Model B programs, which implies the reverse works,
so the **Model C (FPSM + FPRM) is expected to run this Model B code
unchanged.** A future simulator can use these binaries as Model B and
backward-compatibility test programs.

### 3.3 MONITOR

* Banner: `N.E.D. ABLE Series System Monitor - 1 December 1985`.
* Configured for 60K words of memory (configuration table at 74, entry 16
  = 360 sectors), D4567 present.
* The three boot/system disks' `MONITOR` files differ only in word 115
  (configuration entry 17, the options word): each disk carries its own
  configuration.
* Boots in the simulator up to its first floppy access; see
  [`boot-and-loaders.md`](boot-and-loaders.md) §4.

### 3.4 Still not found
* The **MFC/D40Q boot ROM** image. It is not in this disk set.
* A **CPU diagnostic**. None in Release L's diagnostics disk.
* Model C-compiled binaries. A later release, if one turns up, would supply
  them; the `*RTC-7` runtime in `jbemond/Software` is the only Model C code
  so far.

## 4. Reproduce

```bash
git clone https://github.com/Synclavier/Synclavier_Distributions
python3 tools/ned_disk.py Synclavier_Distributions/Release_L/NED_Synclavier_Release_L_DD_Floppies.simg --extract out/
python3 tools/able_disasm.py out/01-BOOTD/.LD-6 --model B | head -40
python3 tools/able_disasm.py out/01-BOOTD/.LD-6 --model B --start 2000 --count 10
```
