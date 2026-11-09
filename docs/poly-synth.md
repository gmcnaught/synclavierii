# Poly sampling synth (D154–D157) — register-level spec from Release 5.3

Scope: what SYN-5.3 (and MONITOR/DEBUG) write to and read from the poly
sampling ("poly synth", PSX/PSC/PSF/PSD) interface, and what they expect
back, so a Python model and later HDL can be built. Source: the NED/XPL
text of Release 5.3 in `out/ned53/` (paths below are relative to it).

Tags: **[OBS]** quoted from source (file:line), **[INF]** inference with the
reasoning given, **[UNK]** not determined from the source.

Notation: XPL `"nnn"` is octal; `READ(x)`/`WRITE(x)` are device reads/writes;
the Able assembler's `im(n)` is octal too.

---

## 1. I/O protocol

### 1.1 Devices

| Device | Name | Role |
|---|---|---|
| D155 | PSC | channel select (write), channel readback (read) |
| D156 | PSF | function code select (write), current FC readback (read) |
| D157 | PSD | data for the selected channel/FC (write and read) |
| D154 | PSX | "extended data" — used only for D/A-controller FCs 64/65 |

[OBS] `SYNLITS/FCODLITS:50-53`.

D51 bit 10 (`1024` = `"2000"`) is the "poly synth exists" bit:
`IF (READ("51")&1024)<>0 THEN DO; /* CHECK POLY SYNTH EXIST BIT */`
[OBS] `SYNSOU/POLYMOD/POLYSOU:1061`, `MONCAT/MON:145`, `SYNRSOU/10-INT/144-TIM3:66`.

### 1.2 Channel number (D155)

* Low 8 bits: `bits 7..6` = bin (0–3), `bits 5..0` = channel within the bin
  (0–63). [OBS] "0=BIN 0, 64=BIN 1, 128=BIN 2, 192=BIN 3" `POLYSOU:176`;
  voice lists are `B.POLY \ (I + 64 * BIN)` `SYNRSOU/08-INIT/600-INIT:1700`.
* SYN-5.3 writes the full 16-bit partial-block channel word, e.g.
  `WRITE(PSC)=MCHN` where `MCHN` carries flag `B.POLY = "010000"` in bit 12
  (`SYNLITS/QUELITS:157`); it masks with `&255` only when indexing tables
  (`144-TIM3:931`). [INF] hardware latches bits 7..0 only.
* Per bin, 64 channel slots exist; slots above the voice count are
  "GHOST/REFRESH CHANNEL(S)" and are still written at init.
  [OBS] `POLYSOU:1101`.
* Memory access selects the bin by writing channel `64*bin`
  ("CHANNEL IS REALLY (64 * BIN #)"). [OBS] `POLYSOU:106,127`.

**Readback of D155** [OBS]:
* bin probe: `WRITE(PSC)=I+1; WRITE(PSC)=I+1; IF (READ(PSC)&"377")=I+1` →
  bin exists (`POLYSOU:1064-1066`; also `STMMOD/STRECSOU:1267-1268`).
* MONITOR compares the **whole word**: `IF READ(PSC) = I + 1` (`MON:148`).
* After `WRITE(PSC)=I; WRITE(PSF)=PSNUMV`, bit 8 (`"400"`) of `READ(PSC)`
  means "NEW D/A CONTROLLER" (`POLYSOU:1126-1128`).
* The timer interrupt saves `READ(PSC)` and `READ(PSF)` on entry and writes
  them back on exit (`144-TIM3:67-68, 1219-1221`).

[INF] Model: `READ(PSC)` = latched channel (8 bits), bit 8 = new-D/A flag
(0 for an old D/A controller; MONITOR's exact compare requires bits 15..8 = 0
at least right after a PSC write). A non-existent bin must not echo the
channel (`POLYSOU:178-181` returns "BIN DOES NOT EXIST").

### 1.3 Function code (D156) and auto-increment

A PSD write stores data into the register selected by (channel, FC) and then
advances FC to a successor. The successor map is fixed per FC:

| Sequence | Evidence |
|---|---|
| 0→1→2→3→4→5→6→7→8→9→10 | [OBS] `POLYSOU:1102-1111`: one `WRITE(PSF)=PSWL` then 11 PSD writes commented WL(2), BA(2), LL(2), PI(2), INC, MOD, ON |
| 16→17→18, 18 stays (data, address++) | [OBS] `FCODLITS:66-71` "writes the first address to PSD; that increments function code to pswma_1 …"; `POLY.OUT` streams PSD writes (`POLYSOU:251-278`) |
| 20→21→22, 22 stays on read (address++) | [OBS] `FCODLITS:72`; `POLY.IN` streams `READ(PSD)` (`POLYSOU:222-249`) |
| 33→35→38→32→34→36→37 | [OBS] `POLYSOU:1114-1118` after `PSF=PSEMOD`: 7 writes commented "MODULUS, INCR / DELTA, COUNT / ENV ACCUMULATOR / LIMIT, CVAL"; same in `MON:167-171`, `301-SUB1:633-637` |
| 35→38 | [OBS] `PSF=PSEINC; PSD=adder; PSD=delta` (`144-TIM3:204-206`, `195-PLAY:249-255`) |
| 36→37 | [OBS] `PSF=PSELIM; PSD=limit; PSD=cval` ("LIMIT, CVAL") `POLYSOU:1118`, `144-TIM3:1057-1061` |
| 40→42→41→43 | [INF] see §3.6: `PSF=PSRCVOL` + 4 writes are always "R cur, L cur, R dest, L dest" (`195-PLAY:176-178,225-234`); `PSF=PSRDVOL` (41) + 2 writes are "RIGHT, LEFT" dest (`352-SPLC:98-112`) |
| 24→24, 25→0, 26→0, 27→28, 28→28 | [OBS] comments `FCODLITS:74-79` (test FCs, unused by 5.3) |
| 10→?, 59→?, others | [UNK]; 5.3 never writes past FC 10, and always rewrites PSF before another FC-59 sequence. `POLYSOU:1081-1085` writes PSF=59 once then `PSC=J; PSD=0` for 16 channels → [INF] FC 59 does not advance and a PSC write does not change FC |

Reads: `POLY.CHECK` reads PSD four times at FC 12 without rewriting PSF
(`POLYSOU:1071-1076`) → [INF] reading FC 12 does not advance FC. All other
envelope/status reads rewrite PSF before each read (`144-TIM3:265-268`,
`352-SPLC:208-213`), so their read-advance behaviour is [UNK] (model: no
advance).

`READ(PSF)` returns the current FC (saved/restored by the interrupt,
`144-TIM3:68,1221`). Because main-level code streams poly memory with
interrupts enabled (`POLY.IN`/`POLY.OUT` do not disable), [INF] writing
`PSF=18` or `22` back must resume the memory stream at the unchanged memory
address, i.e. the memory address counter is independent of the voice
registers and of FC changes. Whether there is one counter per bin is [UNK]
(model: one per bin).

### 1.4 "Two-word" 28-bit values

Wave table length, base address, loop length, phase increment and the memory
address are written as two PSD words:

* word 1 = bits 23..8 (16 bits) — "sector";
* word 2 = bits 7..0 in `[7:0]` ("word in sector"), page bits 27..24 in `[11:8]`.

[OBS] `PSMWRITE`: `WRITE(PSD)=LW(LW#LSB); /* UPPER 16 BITS */`
`WRITE(PSD)=SHL(LW(LW#MSB),8) \ WORD; /* LOWER 8 BITS PLUS PAGE # IN UPPER BYTE */`
(`POLYSOU:129-130`); base address `SHL(XBASE(LW#MSB)&BASE#PAGE_B,8) \ 0`
(`195-PLAY:241`).

Lengths are negative and sign-extended into the page bits:
`TLENW = TLENW | "177400"; /* SIGH EXTEND INTO PAGE BITS */` (`195-PLAY:143`),
`THEN N = N \ "177400"` (`11-TIMB/162-TMB2:1338-1342`); changelog
"Fixed poly ram >> 32mb bugs (sign extend into page bits)" (`195-PLAY:4`).
Examples [OBS]: `-1,-1` = "WAVE TABLE LENGTH OF 1" (`POLYSOU:1103`);
`0,255` = "BASE ADDRESS OF 255" (`POLYSOU:1104`). MONITOR still writes the
old 24-bit form `-1,0` = "LENGTH OF 256" (`MON:158`) → [INF] the pre-1988
controller used 24 bits; a 28-bit model should treat `-1,0` as
`0x0FFFF00`, which only matters for MONITOR's silence routine (voices off).

[INF] Decode: `v = ((w2>>8)&0xF)<<24 | w1<<8 | (w2&0xFF)`, 28-bit two's
complement for lengths. Bits 15..12 of word 2 are ignored.

---

## 2. Poly memory

### 2.1 Organisation

* 16-bit words; samples are 16-bit two's complement. [OBS] crossfade code
  converts to offset binary and back: `LOAD (READ(PSD) XOR "100000")`,
  `/* MAP BACK TO 2'S-COMPLEMENT */` (`POLYSOU:787-792`); init probe writes
  `+32767/-32767` (`600-INIT:1235-1248`).
* Address = page(4) : sector(16) : word(8) = 28-bit word address; 256 words
  per sector. [OBS] `PSMREAD` comment `POLYSOU:100-104`; `SYNAUXS/POLYLITS:8-23`.
* Up to 4 bins (independent subsystems, "ZERO EACH OF 4 POLY BINS"), each
  with its own memory; `PSMAXPAGES = 16` "32MB PAGES … 512 MB TOTAL"
  (`SYNLITS/SAMPLITS:37-38`).
* Software 32-bit pointer: MSB = `bin[15:14] | stereo[4] | page[3:0]`,
  LSB = sector. [OBS] `POLYLITS:8-34`.
* A voice plays only memory in its own bin: channels are allocated from the
  free list of the file's bin (`195-PLAY:28-29`); PSBA carries no bin bits.
  [INF]

### 2.2 Write / read

```
WRITE(PSC) = 64*bin
WRITE(PSF) = PSWMA (16)       ; or PSRMA (20) for reads
WRITE(PSD) = sector           ; FC 16 -> 17
WRITE(PSD) = page<<8 | word   ; FC 17 -> 18 (22 for reads)
WRITE(PSD) = data ...         ; repeated, address auto-increments
x = READ(PSD) ...             ; (read path) repeated, address auto-increments
```
[OBS] `POLYSOU:92-132` (PSMREAD/PSMWRITE), `POLYSOU:222-278` (POLY.IN/OUT,
up to 64 words per `RPC`, i.e. back-to-back transfers at CPU speed).
The address carries across sector (256-word) boundaries: DEBUG dumps many
sectors after one address setup (`DEBUG:199-228`). [OBS]

Disk-to-poly (sound file load) goes through the runtime's POLYREAD:
`R3 to D155 select poly channel here` (`RTP/DISKREAD:986`),
`im(20) to D156` (= 16, PSWMA), `R10 to D157` (sector),
`R11 to D157` (page/word) (`RTP/DISKREAD:37-39`), then `D107 to D157`
per data word, 256 per sector (`RTP/DISKREAD:782-822`). Poly-to-disk uses
`im(24) to D156` (= 20, PSRMA) and `D157 to D107` (`RTP/DISKWRIT:37-39,796-828`).
[UNK] the SCSI driver used for W0 on 5.3 is reached through the device-driver
table (`RTP/DISKREAD:570-597`) and is not in the text source; [INF] it can only
use the same D155/D156/D157 sequence.

"Reset computer interface": `WRITE(PSF)=PSRMA; WRITE(PSD)=0`
(`POLYSOU:1069`, `MON:149`). [OBS] DEBUG warns "PSADC must be reset, or
memory errors occur!" and clears FC 59 on even channels 0–30 before dumping
memory (`DEBUG:193-198`). [INF] an active "even stereo master" interferes
with computer memory access on real hardware; a model can ignore this.

### 2.3 Memory size probe (per bin) [OBS `POLYSOU:1145-1197`]

1. New-controller test: save words 0–1 of page 0 sector 0, write
   `"107070","070707"`, read page 1 sector 0;
   `IF (K <> "107070") & (L <> "070707") THEN NEW.MEM.CTRLR = TRUE`; restore.
2. Count: `POLYAMOUNT` starts at 0 sectors. Loop: at sector `POLYAMOUNT`,
   word 0: save 2 words, write `0, -1`, read back; if both match, restore and
   `ADD16(256, POLYAMOUNT)`; else stop. Caps: new controller stops at
   `PSMAXPAGES` pages (`STR32(15,-1)`); old controller stops when the count
   reaches 65536 sectors (`STR32(0,-1)` = 32 MB).

So `POLYAMOUNT` = memory size in sectors, granularity 256 sectors
(64 K words = 128 KB). [INF] A model with M sectors must make writes beyond
M have no effect and reads beyond M return something other than `0,-1`
(e.g. 0), and must not alias page 1 onto page 0 if it wants to be seen as a
new controller.

### 2.4 Bin header and allocation (software structures in poly memory)

Sector 0 of each bin [OBS `POLYSOU:1371-1391`, `1204-1263`]:
`POLY.MAGIC (12345), POLY.REV (54336), POLYAMOUNT msb/lsb, PSFIRST, PSLAST,
PSMAX, PSFREE, PSHERE` (each 2 words). If magic, rev and amount match at
boot, files from the previous run are kept (users zeroed); otherwise cold
boot: `PSFIRST = FIRST.BASE = 21` sectors, `PSLAST=PSFIRST`,
`PSMAX=POLYAMOUNT`. `PS.LOCK` writes `0,0` at word 0 while memory is being
changed (`POLYSOU:1361-1369`). [INF] zero-initialised model memory → cold boot.

Each loaded file is a block of whole sectors starting at `SFILE.BASE`
[OBS `SYNLITS/SAMPLITS:43-99`]:

| Offset | Content |
|---|---|
| sector 0 | `BL.*` block header: 0 BL.LEN (sectors), 1 BL.USERS, 2–5 BL.FNAME, 6 BL.DEV, 7 BL.SEC, 20–26 KEYTC/VRATE/VDEPTH/VAT/SRATE/PITCH/TOFFS, 27–28 BL.WTABL, 29 BL.SOFS, 30 BL.WOFS, 31–32 BL.LOOPL, 33 BL.ONLOOP, 34–35 BL.MAX, 36 BL.CHECK, 37–38 BL.SFTL, 39–40 BL.SFLL, 41 BL.STEREO, 42 BL.KHZ, 43 BL.SAVED, 63.. BL.LNAME |
| sector 1 (`SF.HDR`) | copy of the sound file header (sector 0 on disk), converted |
| sectors 2–3 (`SF.SYM`) | symbol table (disk sectors 1–2) |
| sector 4 (`BL.POLY`=1024 words) | sample data |

`PS.LOAD` zeroes words `BL.LEN+1 .. BL.POLY-1` and the last sector before
loading (`197-PAL1:422-445`).

---

## 3. Voice model

### 3.1 Per-voice registers (FC 0–10)

| FC | Name | Width / format | Written by 5.3 |
|---|---|---|---|
| 0,1 | PSWL | 28-bit, **minus** total length in words | `-(len)`; 0 for "no length" (`162-TMB2:1302-1312`) |
| 2,3 | PSBA | 28-bit base word address (page:sector:word) | `SFILE.BASE + PT.SOFS` sectors, word `PT.WOFS` (`06-MAIN/304-SUB4:138-143`) |
| 4,5 | PSLL | 28-bit, **minus** loop length in words | 0 when no loop (`162-TMB2:1310-1311`) |
| 6,7 | PSPI | 28-bit phase increment, words per step | word 1 always 0; word 2 `[7:0]` = NOTEADD (`144-TIM3:1001` "UONU&255") |
| 8 | PSINC | 8-bit, written as INC−1 | `NOTEINC` |
| 9 | PSMOD | 8-bit, written as 256−MOD | `NOTENUM` |
| 10 | PSON | bit 0 on, bit 1 loop | 0 off, 1 on/no loop, 3 on/loop (`195-PLAY:264-275`) |
| 11 | PSRON (read) | non-zero while the voice runs | §3.4 |

[OBS] write/read semantics of INC and MOD: `NOTEINC=NOTEINC-1; /* ADJUST TO
MATCH SYNTHESIZER ALGORITHM */ NOTENUM=256-NOTENUM;` (`11-TIMB/137-COMP:185-186`),
inverse `NOTEINC = NOTEINC + 1; NOTENUM = 256-NOTENUM; /* LOGICAL */`
(`137-COMP:236-237`). Init values `PSD=255 /* INCR OF 256 */`,
`PSD=0 /* MODULUS OF 256 */` (`POLYSOU:1108-1109`).

### 3.2 Pitch: rate divider × phase increment

[OBS] `137-COMP:211-214`: "compute sample # based on 101.0101 khz and which
octave note is in": `sample# = t × 101010.1 × NOTEADD × NOTEINC/NOTENUM`.
[OBS] INC=MOD=256 is "100 KHZ" (`06-MAIN/301-SUB1:626-627`).
[OBS] the new poly table (STAB-7, sectors 13–28, 4096 words, `INC<<8 | MOD`,
0 means 256; `SYNLITS/SYNCLITS:112`, `670-SCPT:245-250`) has
entry 3057 = `0x63C8` = 99/200 = 0.495 and `3057 = 50.000 KHZ`
(`137-COMP:138`); entry 4095 = 256/256, entry 3072 = 128/256,
entry 0 = 16/256 (decoded from `W0X/*SYSTEM/*STAB-7.sdat`, big-endian).

[INF] Per voice, a rate generator clocked at F0 = 50 000/0.495 = 101 010.1 Hz
adds INC (logical, 1–256) to an accumulator modulo MOD (logical, 1–256);
each wrap is one step, and each step advances the sample address by PI.
Step rate = F0·INC/MOD ≤ F0 (software keeps INC ≤ MOD, "LIMIT RATIO TO
1.000", `137-COMP:122`). Word rate = step rate × PI. No interpolation is
implied anywhere in the software. Exact accumulator arithmetic is [UNK].

Computation (`COMPUTE.PSYN.FREQ`, `137-COMP:107-188`, new table):
```
fn = FREQ.NUM - (3840-3057)           ; FREQ.NUM 3840 = 50 kHz file at original pitch
i  = fn<0 ? fn&1023 : fn>4095 ? 3072+(fn&1023) : fn
INC,MOD = table[i] (0 -> 256);  PI = 1
if fn >= 4096: PI = 1 << ((fn>>10) - 3)            ; no overflow check
if fn < 0: octaves = (1023-fn)>>10; MOD <<= 1 while <128; INC >>= 1 while even;
           remaining octaves: scaled divide (D4-D7 hardware)
write INC-1, 256-MOD
```
Callers: note start/update `CALL COMPUTE.PSYN.FREQ(BASE+VIBVL+MRLCH)`;
stereo files double PI: `IF UCHN<>0 THEN NOTEADD=SHL(NOTEADD,1)`
(`301-SUB1:197-199`, `381-VIB:247-248`). Audition uses
`2816+LOG1000(SAMPLE.RATE)-LOG1000(500)+1024` (`195-PLAY:146`).
FREQ.NUM is log2 with 1024 steps/octave (`137-COMP:12-16`).
The old-table path (`POLY.FREQ.TABLE.PTR=FRE.PTR`, `137-COMP:113-135`) is
used only when STAB-7 lacks the poly table or the user selects it.

### 3.3 Wave table, loop, end of table

Software computes [OBS `162-TMB2:1290-1350`]:
* no loop info: `PT.ONLOOP=1`, `WTABL = -(max length)`, `LOOPL = 0`
  ("USE 0 AS LOOP LEN FOR NO CLICKS");
* total length TL with loop LL (LL ≤ TL ≤ file length): `ONLOOP = 3` (1 if
  LL = 0), `WTABL = -TL`, `LOOPL = -LL`; stereo lengths forced even.
* Sound-file loop info is "perfect looping file length / loop length"
  (`SAMPLITS:141-142`), i.e. the loop is the last LL words of TL.

[INF] Voice behaviour consistent with this and with §3.4:
```
on PSON write with bit0=1: pos = 0 (offset from PSBA), remaining = PSWL (negative)
per step: out = mem[PSBA + pos]; pos += PI; remaining += PI
          if remaining >= 0:
              if loop bit: pos += PSLL; remaining += PSLL   ; jump back LL words
              else: clear on bit (PSRON -> 0), voice silent
```
[UNK] whether the reset of pos happens on every PSON write or only on an
off→on edge; whether `remaining` is a separate counter or `pos` is compared
with `-PSWL`; exact step at which the end is detected. PSWL may be
rewritten while the voice runs and the new end takes effect: audition while
loading extends `PSWL` after each disk chunk and treats `PSRON=0` as "RAN
INTO END OF THE DATA WE READ IN" (`197-PAL1:618-625,672-688`). Loop
parameters are also rewritten on a sounding voice (`06-MAIN/303-SUB3:446-456`).

### 3.4 On/off, PSRON

* Note start writes `PSON=0` first ("TURN CHANNEL OFF NOW TO PREPARE FOR
  SPLICE"), sets everything, then `PSON = 3/1` in the synchronized start
  loop (`144-TIM3:921-923,1062-1063`).
* `PSRON` (FC 11) read on the selected channel is used as a boolean
  "voice still running" (`195-PLAY:323-325`, `352-SPLC:212-213`,
  `STMMOD/STMPBSOU:135,608`). Comment "READ ON/OFF BITS (UGH!)"
  (`FCODLITS:63`). [INF] returns the channel's on/loop bits; hardware clears
  bit 0 at end of a non-looping table. [UNK] whether it returns bits for
  several channels at once.

### 3.5 Envelope interpolator (FC 32–38)

[OBS] `FCODLITS:81-103`: 12-bit counter PSECNT increments at 25 kHz; at 4096
it reloads PSEMOD ("divide-by-N, N = 4096 − PSEMOD"). On each wrap,
PSEACU += PSEINC (12 bits, remainder kept); when PSEACU wraps, PSEVAL moves
toward PSELIM by PSEDEL. PSELIM range 0–4095.
[OBS] "Envelope delay counter: 00500 counts in 20000 microseconds"
(`FCODLITS:81`).

5.3 values:
* init/cleanup: `EMOD=4095, EINC=4095, EDEL=1 (64 in POLY.CHECK), ECNT=4095,
  EACU=4095, ELIM=0, EVAL=0` (`POLYSOU:1114-1118`, `301-SUB1:633-637`).
* attack/decay: `PSEINC = SHR(EINT&"177400",4)+15` (12-bit adder from the
  timbre's high byte), `PSEDEL = 256/(256-(EINT&255))`, `PSELIM =
  SHL(level,4)` (`144-TIM3:452-471, 965-972`).
* start: `PSELIM=limit`; `PSEVAL=limit` only for a 0 ms attack; otherwise
  `-1` is stacked and the CVAL write is skipped (`WRITE("200")=READ("373");
  WRITE("333")=1;` = load, then relative-skip-if-minus over
  `WRITE(PSD)=READ("300")`), so EVAL ramps from its current value
  (`144-TIM3:979-989,1056-1063`). [INF] from the instruction comments
  "MR13I TO LOAD 0", "IM(1) TO RTMI".
* release: `PSEINC, PSEDEL` then `PSELIM=0`; end detected by
  `PSELIM == PSEVAL` and/or `PSRON==0` (`144-TIM3:196-215,262-268`,
  `352-SPLC:205-214`).
* exponential curves are software: `382-EXP:70-112` reads PSEVAL and
  rewrites PSEDEL/PSEINC ("MIN SLOPE OF 1/16").
* audition / mouse splice: `PSEINC=4095`, `PSEDEL = FAST.RATE 12 ("26 MSEC")`
  or `SLOW.RATE 2 ("160 MSEC")` (`195-PLAY:16-17,249-255`).

[INF] With EMOD=EINC=4095 the step is once per 40 µs and a full-scale ramp
takes 4096/EDEL steps: EDEL=64 → 2.56 ms, matching "DELTA - 2.5 MSEC"
(`144-TIM1:530`); but FAST/SLOW would give 13.7/82 ms against the comments'
26/160 ms (factor 2). See open questions.

### 3.6 Volumes (FC 40–43)

[OBS] `FCODLITS:105-107`: hardware moves current toward destination "at a
rate equal to 1/512 the difference … Reaches 4095 after 1838 counts or
73.520 msecs" (= 40 µs per count, 25 kHz). [INF] A simulation of
`cur += sign · max(1, |dest−cur| >> 9)` from 0 to 4095 takes exactly 1838
steps; `ceil` or exact exponentials give 1391/4609 → use the floor/min-1 form.
Range 0–4095 (`/* SCALE 0-4095 */`, `144-TIM3:949-953`).

Write order [OBS comments]: `PSF=PSRCVOL` then "R, L CVOL", "R, L DVOL"
(`POLYSOU:1120-1122`), "RIGHT, LEFT" twice (`195-PLAY:176-178`);
`PSF=PSRDVOL` then "RIGHT, LEFT" (`352-SPLC:111-112`). Mono voice cards
"ALWAYS PAN HARD RIGHT": `4095, 0, 4095, 0` (`195-PLAY:223-226`).
[INF] successor map 40→42→41→43 (R cur, L cur, R dest, L dest); a linear
40→41→42→43 would make the mono-card write a fade-out on R, contradicting the
comment.

Pan [OBS `144-TIM3:945-956`]: `J = vol·AVOL·filevol`; `R = J·IDAT/16`,
`L = J·(256−IDAT)/16`; cur = dest at note start (no ramp). For a stereo pair
on stereo cards the right-channel voice gets (R,L) swapped
("REVERSE FOR STEREO IMAGE", `352-SPLC:103`).

[UNK] how envelope, volume and sample combine (presumably
`sample × EVAL/4096 × vol/4096` per side) and the DAC width.

### 3.7 Stereo files

[OBS] stereo frames are 2 interleaved words (`samp.len = 2`,
`197-PAL1:210`); CLARA4 (stereo) data starts `0,305,0,314,0,316,1,311`
(two distinct channels interleaved).
Allocation picks an adjacent pair with the **even** channel as left
(`195-PLAY:40-59`). The even (left) voice gets the full setup with PI doubled
and `PSF=PSADEVSM (59); PSD=1` "SET UP THIS CHANNEL AS THE EVEN STEREO
MASTER" (`144-TIM3:974-977`); the odd (right) voice gets
`PSWL..PSPI = 0` (8 zero words), `INC=255, MOD=0`, its own envelope and
volumes, and `PSON=3` (`144-TIM3:888-913`). Cleanup writes
`PSADEVSM=0` on the master (`301-SUB1:644-646`).
[INF] the odd voice is slaved to its even master's address/rate and plays
the odd word of each frame. [UNK] exact slave timing.

### 3.8 Output

[INF] Each voice drives its own D/A (PSNUMV counts "DA CARDS", 4 voices per
card; "MONO DAC VOICE CARDS … NO LEFT DACS ON CARD", `195-PLAY:174-175`) at
its own step rate; voices are summed to the stereo outputs, or routed to
multichannel outputs through D32="21"/D33 using the `MPOLY.PTR` map
(`144-TIM3:925-940`) when `MULTI.THERE`. `PSMUTE (64)` via PSX=0 "TURN ON
D/A"; `PSCMAP (65)` via `PSX=J` "EACH OSCILLATOR TO ITS OWN CHANNEL", only
on a "new D/A controller" (`POLYSOU:1128-1137`). [UNK] mixing, DAC
resolution, output sample rate of the summed signal.

---

## 4. Detection and init

Order: the POLYMOD module body runs `IF INC.POLY THEN CALL POLY.CHECK`
(`POLYSOU:1414`; `inc.poly = 1` in `SYNLITS/somelits:21`). Then
`670-SCPT:204-212` allocates free-voice lists, `600-INIT:1694-1703` fills
them (`B.POLY | (i + 64*bin)`), and the sign-on shows the total
(`680-PRMP:18`).

`POLY.CHECK` (`POLYSOU:1057-1268`) reads, per bin `I = 0,64,128,192`:

| Read | Meaning | Source |
|---|---|---|
| D51 bit 10 | poly present; else nothing below happens | `:1061` |
| `READ(PSC)&255 == I+1` after writing `I+1` twice | bin exists; `POLYNUMS += 1` | `:1064-1067` |
| PSNUMV `[3:0]` | voices = value × 4 | `:1071` |
| PSNUMV bit 4 | envelope card 0 present (else 0 voices) | `:1072` |
| PSNUMV bit 5 | envelope card 1 present (else max 16 voices) | `:1073-1074` |
| PSNUMV bit 6 | A/D controller → PSADMC=0, PSADEVSM=0 on even 0–30 | `:1077-1086` |
| PSNUMV bit 7 | sampling units (STM) → `READ.STM.CONFIG` (PSADID read), PSADMODE/VOL/ACT | `:1087-1099`, `:137-218` |
| `READ(PSC)` bit 8 after `PSF=PSNUMV` | new D/A controller → PSMUTE, PSCMAP via PSX | `:1126-1137` |
| memory probe | §2.3 | `:1145-1197` |
| sector 0 words 0–13 | warm-start header | `:1204-1263` |

Writes in the same loop: all 64 channels get `PSWL..PSON` (11 words:
`-1,-1, 0,255, -1,-1, 0,0, 255, 0, 0`); channels `< voices` also get the
7 envelope words and 4 volume zeros (`:1101-1124`). Ends with `PSC=0`
("avoid shadow register problems", `:1140`).

MONITOR does the same channel/PSNUMV probe and silencing before running
programs (`MON:133-182`). `050-MEM:100-117` silences again (PSON=0,
ELIM/EVAL=0, volumes 0) for all 64 channels of bins with voices.

**No-poly system:** D51 bit 10 = 0 → `POLYNUMS = 0`, `POLYNUMVS = 0`, empty
voice lists, the interrupt does not save PSC/PSF. If D51 bit 10 = 1 but no
PSC echo, the same result. Unguarded accesses remain: `READ.STM.CONFIG(0)`
from STM screens and `AD_INIT` (`STRECSOU:1259-1299`) write PSC and read it
back; a stub that reads 0 makes every bin absent. [OBS]

**Minimal answers for N voices and M sectors in bin 0** [INF from the table]:
* D51 bit 10 = 1.
* `READ(PSC)` returns the last written channel (8 bits, bits 15..8 = 0) for
  channels 0–63, and anything else (e.g. 0) for channels 64–255.
* PSNUMV (FC 12) reads `N/4 | 0x10 | (N>16 ? 0x20 : 0)`, bits 6–7 = 0;
  e.g. N = 32 → `0x38`, N = 16 → `0x14`. N ≤ 32 per bin is what the rest of
  the code assumes (SYNCH.START.BUF sizing `144-TIM3:42-52`, PSCMAP 32 slots).
* Memory: M sectors (multiple of 256), writes beyond M ignored, reads beyond
  M return 0; zeroed at power-on → cold boot. `POLYAMOUNT = M`; usable
  space = M − 21 sectors.
* Example sizes: CLARA3 (mono, 30 001 words) needs a 122-sector block, CLARA4
  (stereo, 60 416 words) about 241; both together need M ≥ 512.

---

## 5. Sound file format (type 5) as the loader reads it

Catalog type 5; sector 0 = header, sectors 1–2 = symbol table, data from
sector 3 (`ls.disk = DSEC + 3`, labels from `DSEC + 1` for 2 sectors,
`197-PAL1:481, 556-568`). Words are big-endian in the disk image.

Header words used [OBS `SAMPLITS:121-156`, `197-PAL1:56-240`, `197-PAL:845-866`]:

| Word | Field | Use |
|---|---|---|
| 0 | sf.compatibility | `<1` → period 600 assumed |
| 2–4 | sf.valid.data (sector msb, sector, word) | end limit, `-1 frame` |
| 9–11 | sf.data.end (s, ms, µs) | end of load (whole-file mode) |
| 12 | keyboard.decay | BL.KEYTC |
| 14–16 | vibrato rate/depth/attack | BL.VRATE/VDEPTH/VAT |
| 18 | sf.hertz (Hz×10) | base pitch → BL.PITCH/TOFFS |
| 21 | sf.period.index (30 MHz ticks; 600 = 50 kHz) | rate if word 42 = 0: `srate = 300000/period` |
| 23–25 / 26–28 | mark.start / mark.end (s, ms, µs) | play region |
| 34–36 / 37–39 | total.length / loop.length (sector msb, sector, word) | loop (words +1,+2 used) |
| 41 | sf.stereo | 1 = interleaved stereo |
| 42 | sf.sample.rate (kHz×10) | 500 = 50 kHz |

Times → word index: `TIME_TO_INDEX` = (s·1000 + ms)·khz10/10 + µs·khz10/10000,
doubled for stereo, split sector/word (`194-SAMP:15-48`).
`LOAD.WHOLE.FILE = 1` (`197-PAL:55`): load from 0 to data.end (or
valid.data − 1 frame). Block length = data sectors + 4 (+1 if partial
sector) (`197-PAL1:274-280`). Files ≥ 65536 sectors are refused
(`197-PAL1:378-386`).

W0 examples [OBS, decoded from the Synclavier³ W0 image]: CLARA3 compat 4,
mono, srate 500, period 600, hertz 4400, valid 117 sectors + 49 words,
data.end 0.600 s, no loop; CLARA4 same but stereo, valid 236 sectors,
data.end 0.604140 s.

After the load, `PS.SETUP` (`197-PAL:833-995`) writes the BL fields:
`BL.WTABL = BL.LOOPL = BL.MAX` = positive length (`SES-SSS+1` sectors minus
word offsets), `BL.SOFS = SSS + 4`, `BL.WOFS = SSW`, `BL.ONLOOP = 1`, loop
info from words 34–39 relative to mark start, `BL.SRATE = log(500) −
log(srate)`. `SETUP.POLY.INFO` turns these into the negative two-word
values of §3.3.

---

## 6. Function codes by phase

**(a) Init** — `POLYSOU:1061-1140`, `MON:145-181`, `050-MEM:100-117`
* writes: PSC; FC 20 (+1 word, reset); FC 0–10 (11 words, all 64 slots);
  FC 33→…→37 (7 words); FC 40→…→43 (4 words); FC 16/17/18 and 20/21/22
  (memory probe, header); FC 58, 59 (A/D present); FC 52, 53, 54 (STM present);
  FC 64, 65 via PSX (new D/A).
* reads: D51; PSC (bits 7..0, bit 8); PSD at FC 12 (×4); PSD at FC 22;
  PSD at FC 55 (STM only).
* `600-INIT:1198-1340` (only with multichannel hardware): FC 16 + 2 data
  words at sector 0 word 254; FC 2,3 (base 255/254); FC 10 = 3; FC 36,37;
  FC 40–43; then probes D33.

**(b) Loading a sound file** — `197-PAL1:336-700`, `197-PAL:833-995`,
`POLYSOU:92-132,222-278,497-532`, `RTP/DISKREAD:37-39,782-822`
* FC 16/17/18: block header zeroing, last-sector zeroing, data via POLYREAD,
  BL fields, bin header (PS.LOCK/UNLOCK).
* FC 20/21/22: PS.SEARCH, PS.SETUP header and first data sector, PS.USERS.
* audition: POLY.PLAY (below) plus FC 0,1 rewritten per chunk and FC 11 read
  (`197-PAL1:618-625,672-688`).
* Garbage collection: COPY.POLY.MEM alternates FC 20 reads / FC 16 writes in
  256-word chunks (`POLYSOU:284-478`).

**(c) Note start / update / stop**
* start (`144-TIM3:838-1003`): per voice FC 10=0; FC 40,42,41,43;
  [stereo slave: FC 0–9 = 0×8,255,0]; FC 35,38; [master: FC 59=1];
  FC 0–5 from partial block; FC 6,7 (0, PI); FC 8, 9.
  Then for all voices started in this tick (`144-TIM3:1050-1066`):
  FC 36 (limit), [FC 37 (cval)], FC 10 (3 or 1).
* audition start (`195-PLAY:110-279`): same registers, plus FC 36 then FC 10.
* pitch update (vibrato, bend, portamento): FC 6,7,8,9 on the master only
  (`301-SUB1:208-211`, `381-VIB:257-259`).
* volume update: FC 41,43 (`352-SPLC:96-113`).
* loop/length edit while sounding: FC 0,1; FC 4,5; FC 10 (`303-SUB3:446-456`).
* initial decay / sustain: FC 35,38; FC 36 (`144-TIM3:452-471`,
  `303-SUB3:267-273`).
* exponential shaping: FC 38; FC 35 (`382-EXP:83-111`); reads FC 37.
* release: FC 35,38; FC 36 = 0 (`144-TIM3:196-215`, `144-TIM1:527-540`).
* end detection reads: FC 36, 37, 11 (`144-TIM3:262-268`, `352-SPLC:205-214`,
  `195-PLAY:85-94,317-333`).
* cleanup (`301-SUB1:610-681`): FC 6,7 = 0; FC 10 = 0; FC 33→…→37 (4095,
  4095, 1, 4095, 4095, 0, 0); FC 40–43 = 0; master FC 59 = 0.
* interrupt entry/exit: read and restore PSC, PSF (`144-TIM3:66-69,1219-1222`).

Never used by 5.3: FC 24–28 (test), 32 and 34 except in the 7-word init
sequence, 44 PSINHON, 48–51, 56, 57, 60, 66 PSRPEAK. [OBS by grep]

**Synclavier³ interpreter hooks near poly code** (no poly register effect):
`interp_usleep` (delays in `POLYSOU:191`, `600-INIT` multichannel probe),
`interp_run_host_250`, `interp_check_interrupts` (`POLYSOU:361-373,414-426`,
copy loops), `interp_poll_for_stop`, `interp_flush_char_output`,
`interp_run_host_non_timer` (`197-PAL*` load/audition), `interp_delay_on_d3_write`
(`600-INIT:948,1627`), `interp_real_time_prefs` (`600-INIT:493,506`).
They are `Native` calls declared in `-XPL/INTRPRTR:36-42`.

---

## 7. Open questions

1. FC successor after FC 10, after 59, and read-advance for FCs other than 12
   and 22 (model: none).
2. Volume FC order 40→42→41→43 is inferred from comments; confirm against
   hardware docs or MAME-style sources if available.
3. Envelope timing: comments give 2.5 ms for EDEL 64 (fits 25 kHz, one
   step per tick) but 26/160 ms for EDEL 12/2 (fits 12.5 kHz). Is the
   counter period `4096−EMOD` or `4097−EMOD`, or does EVAL move by EDEL/2?
4. Exact end-of-table and loop arithmetic (§3.3), when PSON resets the
   phase, and behaviour with PSWL = 0 or PSLL = 0 and the loop bit set.
5. Rate generator arithmetic: is F0 exactly 101 010.1 Hz (9.9 µs) and how do
   INC/MOD wrap (accumulator, remainder)?
6. Stereo slave mechanics (FC 59): does the odd voice read `master_addr+1`
   at the master's step, and does its own PSON matter?
7. PSRON: one channel or a bit field; when it clears.
8. Output mix: sample × envelope × volume arithmetic, DAC width, and how the
   per-voice variable-rate outputs are summed (needed for HDL audio).
9. `READ(PSC)` bit 8 timing (only with FC 12 selected, or always) on a new
   D/A controller; MONITOR's full-word compare suggests 0 otherwise.
10. Memory address counter per bin or global; behaviour of a running voice's
    memory fetches while the CPU streams FC 18/22 (contention).
11. Which driver performs SCSI→poly transfers on 5.3 (device driver table,
    not in the text source).

---

## 8. Model choices (sim/devices/poly.py, hdl/dev/dev_poly.sv)

The open questions above are settled as follows in the model; the HDL is
checked against it read for read (`tests/hdl/test_board.py test_dev_poly`).
Each is a [CHOICE] until hardware evidence turns up.

| Question | Model |
|---|---|
| Configuration | a 3200: one bin, 32 voices (PSNUMV 0x38), 65536 sectors (16M words, 32 MB = one 32 MB page). The 3200 / 6400 / 9600 had 32 / 64 / 96 MB base poly RAM (operator); SYN-5.3 is one program for all three ("Combine 3200, 6400 and 9600 RTP's", `somelits:6`); 6400 / 9600 = 2 / 3 bins [INF] |
| FC after 10, 59, other unlisted FCs; reads | no change; reads never advance FC |
| PSRON (FC 11), PSON read (FC 10) | the selected voice's on/loop bits |
| Ghost channels (≥ voice count) | writes dropped, reads 0; D155 still echoes channels 0–63 |
| Rate generator | 9-bit accumulator: `acc += INC`; if `acc ≥ MOD`: `acc −= MOD`, one step (at most one per 9900 ns tick) |
| End / loop | after a step, if `pos + PSWL ≥ 0`: loop bit and PSLL ≠ 0 → `pos += PSLL` (not below 0), else on bit clears. Comparing `pos` makes a PSWL rewrite take effect at once |
| PSON | bit 0 rising: `pos = 0`, `acc = 0` |
| Envelope / volume clocks | step every 40 000 ns only while EVAL ≠ ELIM or a volume ≠ its destination; settled counters (ECNT, EACU) hold |
| Stereo slave | odd voice of an FC-59 master: plays `mem[master base + master pos + 1]`, does not step itself |
| Output | per voice `mem[base + pos]` (0 when off) × EVAL × volume >> 24 per side, summed, added to the FM output (48 kHz instants), clipped to 16 bits |
| Poly memory at power-on | zero; the HDL writes it all to 0 after reset, 64 bits per write (SYN-5.3 reads the bin header, the size probe's saved words and sectors 22–25 before writing them) |
