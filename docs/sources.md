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
