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

## 4. Progress

* **M7.1/M7.2 (simulator, done):** `sim/cpu.py` Models C and D: D10
  repeat and link, R12 stack, D11 paging, D57. **Correction:** `MR12D`
  stores and *then* decrements R12 (R12 points at the next free word;
  pops are `R12I TO ATNV` then `MR12I`/`MR12`). The earlier
  "pre-decrement" in `instruction-set.md` and `model-c-runtime-analysis.md`
  was wrong; MONITOR 5.3's epilogues crash with it. Docs corrected.
* **M7.3 (simulator, done):** `sim/devices/scsi.py`, D24-D27 and a disk
  target; `tests/sim/test_scsi.py`. MONITOR 5.3 also hand-shakes the last
  byte of each sector itself (D24 peek, ACK on D25).
* **M7.4 (simulator, done):** `sim.boot.boot_from_w0`: the SCSI slot of
  `.SYSTEM/.LD-7` at LOC.LOAD (63K memory: MEM.SIZ 176000), MONITOR via
  ECOPY. D57 = 7 (Model D, D40Q, M64K: MONITOR's `CHECK.MEM.SIZ` wants
  both boards for 63K). The W0 MONITOR's device table also lists a second
  SCSI disk (target 4) and an optical drive (target 1); the boot keeps W0
  and F0 only. Result: "Synclavier System Monitor - 2021/03/09", PROFILE
  runs ("Starting the Synclavier (r)", "Subcatalog USER is not on disk"),
  `Ready >`. SCSI commands used: INQUIRY, TEST UNIT READY, READ
  CAPACITY, READ(10).

* **M7.5 (simulator, in progress):** `PLAY` needs a `:USER` subcatalog
  (MONITOR keeps `.CURRENT`, DO files and history there; Synclavier³
  mounts a separate `USER.simg`); `CREATE USER` on a W0 padded to 30 MB
  (`disk_mb=30`) makes it, through the SCSI write path. Findings on the
  way, all in `sim/cpu.py` with tests:
  * **External memory ≥ 8192 sectors.** SCSILOAD puts a Model D swap file
    at `(EMSIZE − length) AND 174000` (an M512K card boundary); with 4096
    sectors SYN-5.3's 3126 sectors land at sector 0 = page 0 = internal
    memory. A 9600 had several M512K cards; `boot_from_w0` uses 8192.
  * **D2 priority encoder** (Model C/D): read = 2 × highest bit written.
  * **No interrupt right after a PCW write** (Model C/D): RTP/INTRO's
    SREG "this two instruction enable/transfer sequence will NOT be
    interrupted".
  * **D11 holds the page byte only** (low byte reads 0): A.PGX adds a
    byte-swapped negative page delta (low byte 377) and needs no carry.
  * **Poly interface D154–D157**: SYN-5.3 writes D155 without checking
    D51's poly bit; a no-voices stub (`stubs.PolyNoVoices`, [HYP]) accepts
    writes, reads 0.
  * **No interrupt right after a taken absolute transfer** (Model C/D):
    the link (D10) must reach the callee's first instruction (`D10 TO
    MR12D`; SREG: "disable interrupts (preserve D10)"); an interrupt
    there corrupted SYN-5.3's stack.
  **Result:** SYN-5.3 reaches its **Main Menu on a plain VT100 terminal**
  (about 80M instructions, 75 s simulated), "Release 5.3.0 2021/03/09",
  "Current Catalog: W0:", with no unknown device accessed and the poly
  stub untouched after start-up. The menu offers <PF1>/<PF3>/<PF4>
  (keyboard F1/F3/F4) and <BREAK> (Monitor).

* **M7.6 (HDL):**
  * `able_cpu.sv`: Model C/D behind a runtime `model` input (1 B, 2 C, 3
    D), exactly as `sim/cpu.py`; code fetches through `code_cache.sv` (16K
    words, write-through on D62/D63) onto the external memory port.
    Lockstep: random Model C programs (40 × 3000 instructions) and SYN-5.3
    start-up on the system top (2 × 2M instructions, 90 % paged) match.
  * `dev_scsi.sv` (D24-D27 + disk, as `sim/devices/scsi.py`) on SD drive 3;
    `dev_scsi_tb.sv`. D154-D157 answer as the no-voices stub.
  * State image version 2 (`tools/state_image.py`): CPU model, Model C/D
    state, D57, D51 bits, external memory stored / installed (8192 sectors).
    `tools/w0_image.py` makes `W0-53.IMG` (30 MB + USER) and `W0-53.SST`.
  * **Board lockstep** (power-on, state image, MONITOR 5.3, PROFILE, PLAY,
    SYN-5.3 to its Main Menu over the HDL SCSI, DDR3 and SD models): 7.5M
    instructions match the simulator. With the code cache the core runs
    them in 76M clocks (4.75 s at 16 MHz) for 6.24 s simulated time.

* **After M7.6 (simulator and HDL):**
  * **Keyboard:** SYN-5.3 needs no velocity keyboard. `KEYBOARD.CHECK`
    (`08-INIT:610-INI1`) writes CREG 105 and takes `READ(DREG) = 1` as the
    original keyboard (`NEW.ORK = 1`); the ORK model answers 1 (octave 5's
    single key, up). Keys go through `SCAN.ORK.FOR.NOTES`
    (`05-BUTT:076-OLDI`): key = 12 × octave + bit + 12 + `KBD_TRANSPOSE`,
    middle C = key 36 (`SYNC.MIDDLE.C`), so MIDI 60 (midi_in.sv) is middle
    C. Simulator: a key down gives FM voice writes and a note.
  * **Timbres:** SYN-5.3 looks for `.NEWDATA` on the current catalog, then
    the system catalog (`11-TIMB:162-TMB2`), and reports error 4 when none
    is found. `tools/w0_image.py` adds Synclavier³'s `*NEWDATA.stmb` (2000
    sectors, the `.simg` word format) as `W0:.NEWDATA`
    (`ned_disk.add_root_file`, after USER as MONITOR's CREATE places
    files): 8 banks of 250 sectors. Simulator: the Timbre Directory lists
    SIMPLE FM SINE, FM HARMONICS, SIMPLE BELL, … (banks 1, 2, 5); panel
    BANK 1 + ENTRY 2 recalls "SIMPLE FM SINE" over SCSI (3 commands); key
    48 (C5) plays FM HARMONICS / SIMPLE BELL with the carrier at 523.3 Hz.
  * **Panel display "Er":** SYN-5.3 showed "Err4" (above), but the ORK
    model latched display word 0 again on CREG 260 (start the A/D, also bit
    40) right after `LOAD.ORK.DISPLAY`, blanking "r4". The latch is now CREG
    = 40 + I exactly (sim and `dev_keyboard.sv`).
  * **Real time at idle:** SYN-5.3's idle loop makes no SCSI accesses; it
    runs 1717 distinct code words on 5 external pages. The direct-mapped
    code cache indexed with the low address bits missed 300 times per ms
    (pages evict each other: every page starts with the same page-switch
    stub); indexed with `a[13:0] ^ a[23:14] << 4`, 6 per ms (recorded fetch
    stream, 3 s). The throttle's catch-up is now 200 us (was 10 us) so a
    burst of misses is made up instead of lost (the "lag" counter).

* **M7.7 poly sampling:** register-level spec from the NED source in
  [`poly-synth.md`](poly-synth.md) (section 8: the model's choices where
  the source is silent).
  * Simulator (`sim/devices/poly.py`, `boot_from_w0(poly=PolySynth())`):
    SYN-5.3 finds 32 voices and 65536 sectors (32 MB, a 3200); BANK 2 + ENTRY 1 loads
    W0:CLARA3 into poly memory over SCSI (all 30 208 sample words match the
    file, at the voice's base address) and key 45 plays it at INC/MOD
    99/200 = 50 kHz, the file's rate (key 57: 198/200, key 33: 50/202).
  * HDL `dev_poly.sv`: voice rows in block RAM, a rate pass every 9900 ns
    and an envelope pass every 40 us of simulated time (one voice per
    clock); a D157 access waits until the passes have caught up, so reads
    match the model exactly. Poly memory is 16M words (32 MB) of DDR3 (words
    0x1000000 up, shared with D60-D63 and the code cache through an
    arbiter in `synclavier_core.sv`), cleared after reset. Audio: at each
    48 kHz FM sample the sounding voices' words are fetched and mixed in.
    On only when D51 has the poly bit (state images from
    `tools/w0_image.py`; `--no-poly` for none).
  * Checks: `test_dev_poly` (random register streams from the model: every
    read and mix equal, ~3000 reads and ~600 mixes per seed); board-top
    lockstep of power-on, MONITOR, SYN-5.3, CLARA3 recall and a held note
    (20M instructions, 17.4 s simulated, 204M clocks = 12.8 s at 16 MHz).

## 5. NED/Able era check

Release 5.3 must stay a program for NED's own hardware, not for the
Synclavier³ Mac interpreter:
* [OBS] It is Able machine code for the Model D processor (DSM + FPRM,
  NED's 3200/6400/9600 card set, 1988); our CPU model runs it.
* [OBS] Mac support is optional since Release O (WINSTALL history:
  "5/16/88 beta Release O, Macintosh, mouse"); MONITOR tests
  `TERMINAL.MODEL = T#MACINTOSH` and works on a plain terminal (above).
* [OBS] Interpreter hooks are `IM(n) TO RTNV` "native routine" calls
  (`LOADER:SCSILOAD`: "invoke native routine #26 - inform interpreter of
  pending SCSI activity"): a relative transfer *never* — no effect on real
  hardware. Guarded paths use `interp_is_running` (e.g. `10-INT:144-TIM2`:
  "If interpreter is running, don't try to actually measure the D16"),
  so the hardware path is kept.
* [OBS] SYN-5.3 draws its Main Menu with VT100 sequences (plus VT640
  graphics passages, which term_display skips): no Mac terminal needed to
  start. [UNK] Individual screens (e.g. Audio Event Editor, which needs
  Direct-to-Disk) may still assume a Mac.

## 6. Open questions [UNK]

* Model D details beyond `RTP/INTRO`: where `PCI` literals and data
  accesses go while executing from an external page (the interpreter keeps
  `imem` and `memory` apart: [INF] instruction stream from the page, data
  from internal memory); what an interrupt does to D11; external page size
  (64K words [INF]).
* External memory size SYN-5.3 expects; D164; other D57 bits.
* Poly: the open questions of [`poly-synth.md`](poly-synth.md) section 7
  (envelope timing factor, stereo slave timing, output mix and DAC).
* Real-time load: Model D cycle timing (the throttle keeps simulated time;
  the FPGA must run SYN-5.3 faster than real time).
