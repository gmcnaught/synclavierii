# Release 5.3 target (requirements and plan)

The core so far runs **Release L** (May 1986, Model B, floppies; ORK-LM
started from a state image because it needs a Winchester). The new target
is **Release 5.3.0** (build date 2021/03/09), the last NED/Synclavier
Digital release: its binaries ship with Synclavier³, and its **source** is
the MIT-licensed tree we already use (`jbemond/Software`, see
[`sources.md`](sources.md)), so the binary we run and the source we read
match. Why: the later timbre banks (`*NEWDATA.stmb`, the NED libraries)
are in its format (Release L misreads them, [`timbre-libraries.md`](timbre-libraries.md)),
poly sampling is in it, and it boots from a hard disk instead of a state
image.

Tags as elsewhere: **[OBS]** seen in source/binary, **[INF]** inferred,
**[UNK]** open.

## 1. Where the files come from [OBS]

`Synclavier³.app/Contents/Resources/` (the user's Synclavier³ download;
not redistributable here, kept out of the repository like `timbres/`):

| File | What |
|---|---|
| `W0 Disk Image.simg` | 8,794,112 bytes (17,176 sectors): a complete W0: — `MONITOR`, `.SYSTEM` (`CONFIGUR`, `.LD-7`, `.SYN-7`, `.SCOM-7`, `.LOD-7`, `SHUFFLE`, `RECOVER`, …, `.68K`), `PROFILE` (`set rtp syn-5.3 … play`), the real-time programs `SYN-5.3`, `SYN-5.3G` (guitar), `SYN-5.3M`, sound files `CLARA3`, `CLARA4`, diagnostics `DIAGBINS`. `tools/ned_disk.py` reads it unchanged. |
| `WINBOOT.sprg` | 10,416 bytes: the Winchester boot program [INF: `LOADER/SCSILOAD`, below] |
| `*NEWDATA.stmb` | 1,024,000 bytes: a full timbre library in the later format |
| `CLARA3.ssnd` | a sound file |

## 2. What SYN-5.3 needs

| Need | Evidence | Status in the core |
|---|---|---|
| **Model D CPU** (Model C instructions + instruction paging) | `SYNMAINS/COMVK`: "Linking 9600 VK (Model D) version", `com :synmains:bld-daee -p3 -m -d -of :W0:SYN-5.3`; `BLD-DAEE`: `dcl modelc lit 'modelD'`; `MONCAT/MON`: `CONFIGURATION MODELD, MEMORY 63*1024, HAS_BOOT` | Model B, plus ADC/SBB in the simulator (M6 not done) |
| Model C: ADC/SBB, D10 repeat and link, R12 stack (`MR12D`) | [`instruction-set.md`](instruction-set.md) §9 | simulator: ADC/SBB only |
| Model D: **D11 = instruction page pointer** (upper byte effective; page 0 = internal memory, page n = external memory); D10 link and R12 stack used to switch pages; a page-switch stub at the front of internal memory and of every external page | `RTP/INTRO` (PGSW, PGX, SWAP2, A.PGX, C.PGSW: interrupts return through `MR12I TO D11`); interpreter state has separate `imem` (page of instruction memory) and `memory` (`AbleInterpreterStructs.h`); `D57` bit 0 = "Model D exists" (`AbleInterpreter.h`) | none |
| **SCSI** host adaptor D24 (D24 select/data, D25 bus signals, D26 byte, D27 word; `s.c`: `write(mdi)=read(ScsiWord)` reads disk into external memory) and a SCSI disk (W0 at target 5, `CONFIGUR`) | `-XPL` `scsilits`, `D24Sim.h`/`D24SimOSX.cpp` (the Mac runtime's D24 simulation), `LOADER/SCSILOAD`; D51 bit `"40000"` = D24 present | none (floppies only) |
| Boot from W0: the high-memory loader (`FBOOT` load MONITOR, `OVLAY`, `NBOOT`, `CCOPY`, `ECOPY`; swap file into the top of external memory) | `LOADER/SCSILOAD` ("HIGH MEMORY PROGRAM FOR SCSI WINCHESTER SYSTEMS") | the boot loader HLE does the floppy version |
| D57 options (bit 0 Model D, bit 1 D40Q, bit 2 M64K, …) | `AbleInterpreter.h`; `MON` reads `"57"` bit 2 for D40Q | none |
| **Velocity keyboard** on D130/D131 (`new.pan = 1`, `inc.creg = 1`); "no keyboard" handled (`inc.nokbd`) | `SYNLITS/somelits` (the VK flags), `SYNRSOU/08-INIT/610-INI1` | ORK protocol only |
| FM voices D160–D163 (`inc.fm = 1`) | `somelits` | **done** (HDL FM voices) |
| Poly sampling (`inc.poly = 1`, D154–D157) | `somelits`, `SYNAUXS/POLYLITS` | none — later milestone |
| MIDI (`inc.midi`), mouse, multichannel, direct-to-disk, STM | `somelits` | not needed to start [INF] |

## 3. Plan (milestone M7; M6 becomes part of it)

Each step is done in the Python simulator first, then in HDL with the
lockstep check against the simulator, as for Release L.

1. **M7.1 Model C complete (simulator):** D10 repeat counter and link,
   `MR12D`/`MR12I` stack. Check: the MIT runtime paths
   ([`model-c-runtime-analysis.md`](model-c-runtime-analysis.md)).
2. **M7.2 Model D (simulator):** D11 instruction paging, D57. Check:
   the page-switch code of `RTP/INTRO` in small programs.
3. **M7.3 SCSI (simulator):** D24–D27 host, a SCSI disk on the W0 `.simg`.
   Check: `SCSILOAD`'s read sequence.
4. **M7.4 Boot (simulator):** high-level boot from W0 as `SCSILOAD`
   (`FBOOT`), Release 5.3 MONITOR to its prompt, `CATALOG`.
5. **M7.5 SYN-5.3 (simulator):** `PLAY` with the PROFILE; velocity
   keyboard model; reach the main loop; recall an FM timbre from the
   Synclavier³ `*NEWDATA.stmb`; play a note.
6. **M7.6 HDL:** Model C/D in `able_cpu.sv`, D24 + SCSI disk on the SD card
   (`hps_io` image), boot loader W0 mode, VK keyboard from MIDI; lockstep;
   MiSTer hardware test.
7. **M7.7 Poly sampling** (D154–D157 + sample memory in DDR3), after M7.6.

## 4. Open questions [UNK]

* Model D details beyond `RTP/INTRO`: where `PCI` literals and data
  accesses go while executing from an external page (the interpreter keeps
  `imem` and `memory` apart: [INF] instruction stream from the page, data
  from internal memory); what an interrupt does to D11; external page size
  (64K words [INF]).
* Velocity keyboard protocol on D130/D131 (from `610-INI1` and the
  keyboard scan code).
* External memory size SYN-5.3 expects; D164; other D57 bits.
* Whether SYN-5.3 runs without poly hardware (it is compiled with
  `inc.poly`; "Poly Sampling Required" is the per-timbre error in Release
  L).
* Real-time load: Model D cycle timing (the throttle keeps simulated time;
  the FPGA must run SYN-5.3 faster than real time).
