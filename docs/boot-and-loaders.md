# Boot sequence and the high-memory loaders

From NED's loader sources in `jbemond/Software/Able/LOADER` (MIT): FLPLOAD,
WINLOAD, SCSILOAD, the SCSI.LST listing, and the MRGLOAD/NEWMRG build
tools. Plus the *Creating Programs* (1978) and *Scientific XPL* (1987)
manuals. File IDs are in [`sources.md`](sources.md).

## 1. Boot chain

```
 power on / Load button
        │
        ▼
 Boot ROM (on the MFC or D40Q card; the top 4K of the 64K word space)   ← contents NOT in the repo
        │  reads the high-memory loader from the boot device
        ▼
 ".LD-7" high-memory loader, 768 words, resident in the lower 768 of the
 upper 1024 words of usable core (MEM.SIZ − 1024 …)
        │  entry 0: FBOOT – read catalog, load the file 'MONITOR'
        ▼
 MONITOR (the operating system), then user programs via OVERLAY
```

* **Operator view (1978):** insert the system disk, press **Load** on the
  front panel, and the terminal prints `READY`. A beep means a bad or wrong
  system disk.
* **Memory map (XPL manual, App. F):**
  * internal memory is 16K–64K words, 60K in a Synclavier
  * the **top 4K is the "Bootload ROM"**
  * just below it sit the system state variables, the overlay routine (this
    loader) and the high-core configuration table
* *Cards and Components* says the load button "activates firmware on the
  MFC or D40Q 'maxi' or 'mini' ROMs, or a hard-wired boot ROM". **That ROM is
  not part of the CPU cards, and its source or image has not been found.**
* **What the ROM does** (NED's `Able/UTILCAT/WINBOOT` source): *"When this
  diskette is placed into F0 and the LOAD button is pressed, this program
  will be loaded by the ROM loader."* The program is saved under the name
  `MONITOR`. **So the boot ROM reads the F0 floppy catalog, loads the file
  named `MONITOR` and starts it.** MONITOR (or the `.LD-x` it relies on)
  takes over from there. WINBOOT is NED's trick to boot a Winchester via a
  floppy `MONITOR` that chains to `W0:MONITOR`.

### Synclavier³ / emulator software

* NED's MIT-licensed source tree (`jbemond/Software`) contains **no boot ROM
  image** and no ROM emulation. The host-side XPL runtime
  (`AbleRunTime/XPLRunTimeOSX.cpp`, `set_up_able_core`) builds the
  **post-boot state directly in C**:
  * a low-core configuration table, with the processor type set to Model D
    plus multiply/divide
  * high-core MONITOR variables: catalog pointers for `W0:`, `loc_magic` =
    12345, run status 2, prompt `Ready > `

  That is high-level emulation of the boot, so a re-implementation can do
  the same instead of needing the ROM.
* The Synclavier³ product replaces the CPU entirely ("D0 PCI Synclavier³
  interface card … replaces the computer in the bin"; the FPRM, DSM and D4567
  can be removed), so it has **no reason to contain the MFC/D40Q ROM**. Its
  CPU-interpreter core is not in the public source; only the headers are.
* The commercial binaries were **not** examined: they are proprietary, and
  extracting from them may breach their licence. If ROM images or the
  interpreter core are wanted, the clean route is to ask Synclavier Digital,
  who MIT-licensed the rest of the software in 2017.

## 2. The loader image

> **Compiled `.LD-7`:** `jbemond/Software/Able/W0X/*SYSTEM/*LD-7.sdat` (MIT;
> byte-identical to `Able/LOADER/HIGHLOAD`) is 2165 words: three 768-word
> loaders (floppy at 0, IMI at 1400, SCSI at 3000 octal), each starting with
> the relative-jump vector. Its SCSI slot is an **older revision** than the
> `SCSI.LST` listing (which includes a 1994 change). The words match up to
> offset 262, apart from two in-line offsets, then shift because of inserted
> code.

> **Real binary check:** Release L's `.LD-6` (1986, three 512-word loaders
> for floppy, IMI and SCSI at offsets 0/1000/2000) disassembles to exactly
> this structure. See [`release-l-image.md`](release-l-image.md).


`HIGHLOAD` is built by MRGLOAD from three 768-word routines, one per boot
medium:

| Routine | Medium | Devices used (octal) |
|---|---|---|
| `FLPLOAD` | floppy (D100/D100A) | D100–D104 (controller), D60/D61/D63 (external memory), D50/D51 (terminal), D1 |
| `WINLOAD` | IMI Winchester | D105–D107, D60–D63, D4–D7, D50 |
| `SCSILOAD` | SCSI Winchester (D24) | D24–D27, D60–D63, D4–D7, D50, D3 |

Each routine starts with the same **five-entry jump vector**:

| Offset | Entry | Function |
|---|---|---|
| 0 | `FBOOT` | load `MONITOR` from drive 0 |
| 1 | `OVLAY` | overlay a program (AC0/AC1 = sector, AC2 = destination, AC3 = length) |
| 2 | `NBOOT` | load the file named in R0–R3 |
| 3 | `CCOPY` | core-to-core copy |
| 4 | `ECOPY` | external memory → core copy |

Each entry first does `IM(-20) TO D1`, writing the PCW to make sure
interrupts are off. The listing shows the vector as `RE(FBOOT) TO RTRA` and
so on: **relative** jumps, so the loader is position-independent.

## 3. Device interfaces documented on the way

### D4567 hardware multiply/divide (devices 004–007)

The SCSILOAD source shows the register protocol:

| Operation | Sequence |
|---|---|
| Divide 32 ÷ 16 | `lo → D5`, `hi → D4`, `divisor → D7` (starts the divide); then `D5` = quotient, `D4` = remainder |
| Multiply-add | `a → D5`, `addend → D4`, `b → D6` (starts the multiply); then `D5` = low result, `D4` = high result (a × b + addend) |

### D24–D27 SCSI host adaptor

| Device | Use |
|---|---|
| D24 | select (`SELENA` 10000, select mask 7400) and data (377) |
| D25 | SCSI control signals; arbitration (ARB6 5000 / ARB7 1000) |
| D26 | extended read command (50) |
| D27 | status (busy 4000, mask 7400) and data |

### D60–D63 external memory

**D60 = sector address**, **D61 = word pointer within the sector**, and
**D63 = data port**: successive `MR0I TO D63` / `D63 TO MR1I` copy
consecutive words, so it auto-increments. The Model C interrupt routine saves and restores D60/D61 when
swapping code is present (compiler, `l_in2`/`l_in3`).

## 4. What this means for the CPU cards

* The **FPSM INITROM** only has to bring the processor to the documented
  reset state (PC = R17, interrupts off). Loading software is done by the
  separate boot-ROM card (MFC/D40Q), which drives the bus like any other
  agent (compare the HOP).
* A reset/boot model of the CPU needs: the INIT behaviour, the boot-ROM card's
  ROM image (missing), and the `.LD-7` loader (available as source; it can be
  assembled or taken from a disk image).
* **Missing pieces:** the MFC/D40Q boot ROM contents; how the Load button
  starts execution (HALT/HOP-style takeover, or a reset vector into the ROM).
