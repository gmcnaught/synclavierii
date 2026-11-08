# Sources (pinned)

Each source this project relies on, with enough identifying information to
find the exact same file again if links move. Retrieved 2026-11-07. None of
these files are redistributed here.

## Primary: NED documentation

### ABLE Series Hardware Reference Manual (60 pp. scan)

| | |
|---|---|
| archive.org | `https://archive.org/download/Synclavier-docs/Documentation/Technical%20Documentation/ABLE%20Series%20Hardware%20Reference%20Manual/Development/Hi%20Res%20Scans/ABLE_Series_Hardware_Ref_Manual.pdf` |
| GitHub | `Synclavier/Documentation` @ `ee74dbdc1ea30e9344c01a2e7618e210aded8433`, path `Technical Documentation/ABLE Series Hardware Reference Manual/Development/Hi Res Scans/ABLE_Series_Hardware_Ref_Manual.pdf` (blob `c694446bffa9b78f21b2e150137a8b9762694d9b`). Same file as the archive.org copy. |
| Size | 5,778,345 bytes |
| MD5 | `227885b30447773a12c8c41be02cdedd` |
| SHA-1 | `b5cd7fa8e98af9b2e835b6bd5284480862f58b84` |
| SHA-256 | `0c642bd21f8994cc517d93005031e7424bf639e82843c252dfaa5f9422320218` |

Page map (printed page → PDF page) for the parts used:

| Content | Printed | PDF p. | Used in |
|---|---|---|---|
| Introduction: registers, buses | 1-1 … | 3–4 | instruction-set §1, able-reference §1 |
| Processor products (D1 Sequencer, D300 Register Module) | — | ~8 | able-reference §1 |
| Central processor, C/Z/M flags | 2-2, 2-3 | ~12–13 | able-reference §1 |
| **Source/destination code table** | **2-5** | **15** | instruction-set §2 |
| Fig. 1 Structure of ABLE Series Computers | 2-7 | 17 | able-reference §1 |
| **Fig. 2 Structure of Sequencer & Register Module** | **2-8** | **18** | able-reference §1, board READMEs |
| Micro-cycle | 2-9 … 2-11 | 19–21 | instruction-set §7 |
| **Source and destination details** | **2-12 … 2-25** | **22–35** | instruction-set §2–6 |
| HOP, PSW, PCW, interrupts | 2-26 … 2-31 | 36–41 | instruction-set §8 |
| **EZbuss Table 1 (72-pin pinout)** | **A2-4** | **45** | able-reference §3, `data/ezbuss-pinout.csv` |
| Read/write timing, interface examples | A2-5 … | 46–51 | able-reference §1 |
| System timing (asynchronous, ~180 ns, ~250 ns) | A3 | 54–56 | instruction-set §7 |
| **Device address map** | App. IV | **58** | instruction-set §8 |

### Synclavier Internals (NED internal, 19-Jun-1987)

| | |
|---|---|
| archive.org | `…/Technical%20Documentation/Synclavier%20Internals%20Documentation/Development/Hi%20Res%20Scan/Synclavier%20Internals.pdf` |
| Size / MD5 / SHA-1 | 7,179,121 bytes / `16385665c5fab4fa0add2b9cfd261855` / `820fa84e65602e0c7b9086b6d977daeef24929cb` |
| Used | §5 "Hardware overview": device list; glossary entry `RPT` (Model C microcode) |

### Scientific XPL Reference Manual (NED, June 1987)

| | |
|---|---|
| archive.org | `…/Technical%20Documentation/Scientific%20XPL%20Reference%20Manual/Public/Scientific%20XPL%20Reference%20Manual%20OCR%20Lo-Res.pdf` (OCR text `…_djvu.txt`) |
| Used | §VIII "Hardware Manipulation" (READ/WRITE, in-line assembly example `r0 = "300"`, `add0 = "210"`; a missing device halts the CPU); §IX interrupts (WHEN identifiers); fixed-point timing (about 1 µs per instruction; D4567 multiply about 2 µs); shift timing; Model B/C module incompatibility (p. 79) |

### Creating Programs for ABLE Series Computers (NED, Oct 1978)

| | |
|---|---|
| archive.org | `…/Technical%20Documentation/Creating%20Programs%20for%20ABLE%20Series%20Computers/…` |
| Used | Boot procedure (system disk, Load button, READY); compiler memory-map output. Otherwise an OS user guide. |

## Primary: NED software sources (MIT licence)

GitHub **`jbemond/Software`** ("Official Software for the Synclavier® Digital
Audio System", © 2017 Synclavier Digital, MIT licence) @
`a237bf2a6698bf7bc6c8282227fc22b627e512cc` (2018-07-21). The `Able/` tree
was imported from a SCSI drive used at NED. Files are CR-terminated and have
no extension.

| File (blob) | Used for |
|---|---|
| `Able/ASM/ASM-2` (`39079b02…`): NED ABLE Series Assembler v2.07, 1 Apr 1989, `configuration modelC` | **Official mnemonics** (`LOA`, `RTL`, `LCM`, `TLOA`, `BSOR`, `SHRA`, **`ADC` 270**, **`SBB` 274**, `ATRA`…`RTPL`, `PCI`, `Rn`, `RnI`, `MRn`, `MRnI`, **`MR12D` = 372**, `Dn`, `IM`, `RE`) |
| `Code/Includes/Able Interpreter/AbleInsructions.h` (`2f9f0f97…`) | Instruction field constants; BSOR/SHRA marked "(model B)"; `b_adc 0xB8`, `b_sbb 0xBC` |
| `Code/Includes/Able Interpreter/AbleInterpreterStructs.h` (`87a11d236ab4`) | Interpreter CPU state: `rpc` "repeat counter", `ppc` "prior program counter" (the two D10 registers), `zflags` (Z/M from one result word), `carry`, `psw`, `d4567` |
| `Code/Sources/XPLProcessors/pass2.cpp` (`faf98fe3…`), `pass3.cpp` (`b807143f…`) | Model C code generation: **`d10` repeat counter**, "save return (D10)" in WHEN, R12 stack with `mr12d`/`mr12i`, "zflags garbage after call on Model C"; Model D external-memory paging |
| `Able/-XPL/SYSLITS` (`06313fdf…`) | `processor_type` (0 A, 1 B, 2 C, 3 D); `o#d4567` option bit |

| `Able/*SYSTEM/*RTB-7.sdat` (`1cee93eab756`), `*RTC-7.sdat` (`1ff6069f459f`), `*RTD-7.sdat` (`7939477257eb`) | Compiled XPL runtime packages for Models B/C/D, disassembled in [`model-c-runtime-analysis.md`](model-c-runtime-analysis.md) |
| `Able/LOADER/SCSI.LST` (`7ed9f580cc21`; SHA-256 `83149c2fbf42aeb0…`) | NED assembler listing; **disassembler validation fixture** (`tests/fixtures/NED-SCSI.LST`, redistributed under MIT) |
| `Able/W0X/*SYSTEM/*LD-7.sdat` (`0d20fd48681d`; same as `Able/LOADER/HIGHLOAD`) | Compiled `.LD-7` high-memory loader (3 × 768 words) |
| `Able/UTILCAT/WINBOOT` | "loaded by the ROM loader" when F0 + LOAD: the boot ROM loads the file `MONITOR` |
| `Code/Sources/AbleRunTime/XPLRunTimeOSX.cpp` (`set_up_able_core`) | Host runtime synthesises the post-boot low-core/high-core state (no ROM) |
| `Able/RTP/DISKREAD` (`31e6bd1cd120`), `DISKSEEK` (`ed70f267b664`); `Able/XPL/DEVUTIL` (`f2701f8292dc`) | XPL runtime floppy driver (D100–D104 commands, status masks, sector→cylinder/side/sector mapping, alternate motor speed beyond 5 × 80 sectors); `d100_disk_check` (index pulse, D3 read) |
| `Able/MONCAT/MON` (`9f78ba6bf098`), `01-DEFS` (`85dc9e335958`), `11-MAIN` (`e0996ee5b53d`) | MONITOR source (later release): `COLD.BOOT`/`WARM.BOOT`, magic-number check, memory-size words written before overlays, `BOOT` command jumps to the ROM at 176000 |
| `Able/LOADER/FLPLOAD` (`f15efb098d69`), `SCSILOAD` (`229ac2c68340`), `WINLOAD` (`ccf40fd24b15`), `MRGLOAD` (`97887427fa70`) | High-memory loaders and the HIGHLOAD build ([`boot-and-loaders.md`](boot-and-loaders.md)) |

The ABLE interpreter's execution core (`AbleInterpreterCore` implementation)
is **not** in this repo; only its headers are.

## Primary: NED distribution image

GitHub **`Synclavier/Synclavier_Distributions`** @
`c01668b6d44b13b5b88a88d34d87c9c4fafc5c0f`,
`Release_L/NED_Synclavier_Release_L_DD_Floppies.simg`: 5,242,880 bytes,
SHA-256 `97bb43decb64a497206661fc3b9e08377cc00bf58a52aef396196ce1828a1db0`.
19 Release L floppies (June 1986). **No licence file** in that repo, so
nothing from it is redistributed here. Analysed in
[`release-l-image.md`](release-l-image.md).

Format cross-reference: `hansliss/syncextract` @ `d370916ed4dc`.

## Secondary: community

### "Cards and Components – Description.docx" (M. Waluga, 04/2023)

| | |
|---|---|
| GitHub | `Synclavier/Documentation` @ `ee74dbdc…`, path `Technical Documentation/Synclavier Internals Documentation/Cards and Components - Description.docx` (blob `a5dd4059a1e60ccc513d9f66122e0e18b0605ccf`) |
| SHA-256 | `890baafd65755f82f9760dd7749799fae13b6b69d14d591a026f9d78d6d23d8e` |
| Used | Model B/C/D card pairs; "FP" = Fast Processor; slots 13/14 in the 25-slot bin; D3 clock sources; M64K needs Model C |
| Caveat | A compilation from many sources; the author asks for corrections. Treat it as secondary. |

### Forum, web pages

| Source | Used for |
|---|---|
| [Vintage Synth Explorer: "1982 Synclavier II HxC Retrofit!", p. 2](https://forum.vintagesynth.com/viewtopic.php?t=80036&start=15) | FPRM-185 = registers + 4× 74F181 ALU; field repair by card swap |
| [macthenaief: ABLE](https://sites.google.com/site/macthenaief/Home/retro/able) | ISA summary; pointer to the "FAB" VHDL re-implementation |
| 500sound.com `/software/techdata.html` | reportedly says NED produced no service manuals. **Unreachable when checked; unverified.** |

## Board photos (studiorepair.com, © STUDIO REPAIR)

Gallery: <http://studiorepair.com/gallery/misc/NED_Synclavier_II/index.html>.
All are 822×622 px; no larger originals are online.

| Photo | URL path under `…/NED_Synclavier_II/slides/` | SHA-256 |
|---|---|---|
| FPRM-185 component side | `NED_Synclavier_II_PCB_FPRM-185_CS__STUDIOREPAIR_08081501_1005214805.JPG` | `2d0b395fd9eb657e0a1a3fa3519f9c48f4a49ccd680ef7e0eb124ca54cc45222` |
| FPRM-185 solder side | `NED_Synclavier_II_PCB_FPRM-185_SS__STUDIOREPAIR_08081501_1005214806.JPG` | `67a9fc49daf9b6eab1772acf704f82fa69a75fc8c81241e7d7f6ac798f6bc1ee` |
| FPSM-185 component side | `NED_Synclavier_II_PCB_FPSM-185_CS__STUDIOREPAIR_08081501_1005214803.JPG` | `108e4dfdecfc2d149937064d0b6541a29bc55716a9adb32b0391f55467db07cc` |
| FPSM-185 solder side | `NED_Synclavier_II_PCB_FPSM-185_SS__STUDIOREPAIR_08081501_1005214804.JPG` | `0476606f22d2c853ec0beda024d0ae6acdf2d61ac16acd238459ae10e3403408` |
| Bus plane (backplane rear) | `NED_Synclavier_II_Bus_Plane__STUDIOREPAIR_08081501_1005234889.JPG` | `f7a5eb4546bbaa1e1b715320880e123f4545af0ddef4ef1c7b12c341fc477d10` |
| Main frame with cards (slots numbered to 32) | `NED_Synclavier_II_Main_Frame_Guts__STUDIOREPAIR_08081501_1005194686.JPG` | `1a000c3d7701868eda42f7d5f1286d2a7a2613380a9292520eb8ee2679b9e19f` |

The copies analysed in this project were supplied by the owner. They show
the same boards and framing as the URLs above, but are re-encoded, so their
checksums differ.

## Owner-supplied information (no document cited)

* FPRM = Register Module; FPSM = Sequencer Module; partners.
* The cards communicate through the backplane; J1 ribbons go to other cards.
* The cards must be in strictly adjacent slots; the backplane is referred to
  as "IB25"; peripherals (MFC1, disk controllers) cable out of the rack.
