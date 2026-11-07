# FPSM-185: Fast Processor Sequencer Module (ABLE Model C CPU)

> **Status: first pass from photos only** (component side and solder side,
> 822×622 px, studiorepair.com). Part markings are mostly readable. The
> netlist is inferred: **[STD]** = standard topology, **[OBS]** = seen in the
> photo, **[HYP]** = hypothesis to check with a meter.

**Partner board:** [FPRM-185 Register Module](../fprm-185/README.md).
The two cards together make up the CPU. The FPSM is the **control unit**:
microcode store, micro-sequencer, instruction dispatch, interrupt
prioritisation and bus timing. It drives the FPRM **through the shared
backplane bus**: it puts 8-bit operation codes on ADR0–7, asserts RD̅ or WR̅,
and waits for SYN̅. The 34-pin ribbon on J1 goes to *other* external cards,
not to the FPRM.

| File | Contents |
|---|---|
| [`bom.csv`](bom.csv) | Bill of materials with a confidence rating for each line |
| [`schematic-block.svg`](schematic-block.svg) | Block-level schematic |
| `README.md` | Layout, inferred netlist, FPRM↔FPSM backplane interface, verification plan |

---

## 1. Board overview

* **Board:** New England Digital Corp. **FPSM-185**. The UL mark on the solder
  side reads `94V-0`. Someone has written "12-2" on the component side, which
  may be a revision or a test/date mark.
* **Logic:** a mix of Fairchild/Motorola **74F** and TI **74LS/ALS**, three AMD
  **Am29823** 9-bit registers and one tapped delay line. Date codes are
  8513–8642 (1985–86).
* **Seven socketed, labelled PROMs (©1986 N.E.D.):**

  | RefDes | Label | Pins | Probable role |
  |---|---|---|---|
  | U61 | `SMR00` | 24 | Microcode ROM, bits 0–7 |
  | U71 | `SMR01` | 24 | Microcode ROM, bits 8–15 |
  | U81 | `SMR02` | 24 | Microcode ROM, bits 16–23 |
  | U51 | `SMR03` | 16 | Microcode ROM, bits 24–27 (×4 part) |
  | U22 | label destroyed (`REV. B`?, blue pen) | 24 | Opcode decode/dispatch |
  | U23 | `DDE…2` | 24 | Opcode decode/dispatch |
  | U42 | `INITROM` | 16 | Power-up / trap vector |

  "SMR" plausibly stands for **S**equencer **M**icrocode **R**OM. **Read all
  seven and archive the contents before doing anything else.** They are the
  CPU's microprogram, and the board cannot be rebuilt without them.
* **Clock:** U93 is a tapped delay line marked `DL15C60D` (or similar). Next to
  it is a jumper field labelled `40 50 60 70 80` and `CLK`, which selects the
  delay tap used for the clock. Record which tap is linked.
* **Rework:** two resistors are soldered on the solder side near U36–U38.
  Record their values and both ends.

### What the board is

**FPSM = "Fast Processor" Sequencer Module, the sequencer half of the Model
C processor** (Model C = FPSM + FPRM). It was used in the PSMT, all
Direct-to-Disk and Poly systems, and some Synclavier IIs. Model D replaces
this card with the **DSM** and keeps the FPRM. It sits in **slot 14** of the
25-slot computer bin, next to the FPRM in slot 13
([`docs/able-reference.md` §5](../../docs/able-reference.md#5-processor-models-and-slot-placement-cards-and-components-2023)).
No public schematic or microcode dump was found, so the SMR/DDE/INITROM
contents can only come from reading a physical board.

### Documented role (ABLE Hardware Reference Manual)

The manual's Fig. 2 shows the **Sequencer** as:

* an *Instruction Register* and a *Data Register*, both loaded from the data
  bus (the fetched word goes into both)
* a decode/state block
* a *Selector* that puts either the source half or the destination half of
  the instruction on **ADR0–7**
* the IRQ̅, HALT̅/HAK̅, SYN̅, RD̅ and WR̅ lines
* the C/Z/M flags as an input from the Register Module

Each instruction is fetch → source READ → destination WRITE, with
immediate sources and failed conditional transfers shortening the cycle
([`docs/instruction-set.md` §7](../../docs/instruction-set.md#7-execution-model-pp-2-6-2-9-to-2-11)).

| Documented block | This board **[HYP]** |
|---|---|
| Decode / state | Microcode SMR00–03 + pipeline registers (a microcoded "Model C" implementation, per *Synclavier Internals*) |
| Instruction decode | U22/U23 "DDE…" PROMs (instruction → microcode entry address) |
| Instruction Register and Data Register | U12/U13 74F374, U24 Am29823, U14 74F245 on BDB0–15 (exact split unknown) |
| Selector → ADR0–7 | U43–U47 '153 (S field / D field / PC register code / device code) or U2/U3 'LS374 → edge |
| IRQ̅, HALT̅, SYN̅ in; HAK̅, RD̅, WR̅ out | U1 74LS240 / U4 74F240 inverting receivers (negative-logic bus); U38 74F38 / U54 7438 open-collector drivers (the manual recommends 7438-type drivers) |
| C/Z/M flags from the FPRM | EZbuss **pins 62/64/60**, private to the CPU slot pair → U31 '151 condition select |
| About 180 ns from address to RD/WR, no system clock | **U93 delay line + JP1** set the delays and strobe widths |
| IRQ̅ sampled at the end of each instruction; PC switches to R16; ACK̅ on PSW read | U34/U35 'LS348, U36 'LS174, INITROM |

---

## 2. Physical layout (component side, J1 on the left, edge on the right)

```
 col 9          col 8         col 7          col 6          col 5          col 4            col 3            col 2         col 1 (edge)
                U81 SMR02*    U71 SMR01*     U61 SMR00*     U51 SMR03*     U41 74F241       U31 74F151                     U1 74LS240
 J1  U91 Rnet   U82 74F374    U72 Am29823    U62 Am29823    U52 74F175     U42 INITROM*     U32 74ALS161     U12 74F374    U2 74LS374
 34p U92 Rnet                                                              U43 74F153       U33 74ALS161     U13 74F374    U3 74LS374
                              U73 74F08      U63 74F00      U53 74F74      U44 74F153       U34 74LS348      U14 74F245    U4 74F240
     U93 delay                U74 74F04      U64 74F02      U54 7438       U45 74F153       U35 74LS348
     line + JP1                                                            U46 74F153       U36 74LS174      U22 PROM*
                                                                           U47 74F153       U37 74LS00       U23 DDE PROM*
                                                                           U48 74LS04       U38 74F38        U24 Am29823
                                                                                                     (* socketed, labelled)
```

Each microcode PROM sits directly above its pipeline register: SMR00→U62,
SMR01→U72, SMR02→U82, SMR03→U52. That layout is good evidence for the
pipelined microcode architecture described below.

---

## 3. BOM summary

The full BOM is in [`bom.csv`](bom.csv). **Total: 41 ICs, of which 7 are
programmed PROMs**, plus 2 DIP resistor networks.

| Qty | Part | Function | RefDes |
|---:|---|---|---|
| 5 | 74F153 (3× Motorola MC74F153N, 2× Fairchild) | Dual 4→1 mux | U43–U47 |
| 3 | Am29823 | 9-bit register | U24, U62, U72 |
| 3 | 74F374 | Octal D-FF | U12, U13, U82 |
| 2 | 74LS374 | Octal D-FF | U2, U3 |
| 2 | 74ALS161 | 4-bit counter | U32, U33 |
| 2 | 74LS348 | 8→3 priority encoder | U34, U35 |
| 1 | 74LS174 | Hex D-FF | U36 |
| 1 | 74F175 | Quad D-FF | U52 |
| 1 | 74F151 | 8→1 mux | U31 |
| 1 | 74F74 | Dual D-FF | U53 |
| 1 | 74F245 | Transceiver | U14 |
| 1 | 74F240 / 1 74LS240 | Inverting buffer | U4 / U1 |
| 1 | 74F241 | Buffer | U41 |
| 1 each | 74F00, 74F02, 74F04, 74F08, 74LS00, 74LS04 | Glue | U63, U64, U74, U73, U37, U48 |
| 1 / 1 | 74F38 / SN7438 | Open-collector NAND buffer | U38 / U54 |
| 7 | Programmed bipolar PROMs | See §1 | U22, U23, U42, U51, U61, U71, U81 |
| 2 | 16-pin DIP resistor network (yellow, `4116R-001-10x`?) | Series termination for J1 ribbon lines | U91, U92 |
| 1 | Tapped delay line `DL15C60D` | Clock timing | U93 |
| ~42 | 0.1 µF (`ESK104`/`KLK104`) | Decoupling | C2–C43 |
| 1 | Tantalum, axial | +5 V bulk | C1 |
| 1 / 1 / 1 | Resistor / glass diode / brown dipped cap | Reset or misc? | R1 / D1 / C28 |
| 1 | 34-pin IDC box header | Ribbon to other external cards | J1 |

---

## 4. Inferred architecture & netlist

### 4.1 Power **[STD]**
VCC is pin 14/16/20/24 and GND is pin 7/8/10/12 for 14/16/20/24-pin parts.
Exceptions: the Am29823 (24-pin 0.3") uses VCC = 24 and GND = 12. For the
PROMs, check against the datasheet once the parts are identified.

### 4.2 Microcode store and pipeline **[OBS] + [HYP]**
* **SMR00–SMR02** are 8 bits wide and **SMR03** is 4 bits wide, giving a
  **≈28-bit microword**. All four share one microaddress bus **[STD]**.
* The pipeline register is clocked on each microcycle. Each PROM's outputs
  feed the register below it:
  `SMR00 → U62 (Am29823)`, `SMR01 → U72 (Am29823)`, `SMR02 → U82 (74F374)`,
  `SMR03 → U52 (74F175)`.
  The Am29823's CLR̅ and EN̅ pins would let the sequencer clear the microword
  (a NOP) or hold it (a wait state).
* Microword fields **[HYP]**:
  * bus-cycle control: which IAB code to drive (S field, D field, R17 for
    fetch, 001 for PSW …), RD̅ vs WR̅, and when to wait for SYN̅
  * IR/DR load enables, the immediate sign-extend path, and skipping steps
  * next-address select, branch address, condition select (to U31)
  * interrupt and HALT handling, and Model C extensions such as `RPT`

  The FPRM decodes its own operation from the IAB code, so the microword
  does **not** need to carry ALU S0–S3/M control.
* **Microcode depth** depends on the PROM type. The 16-pin ×4 SMR03 suggests
  256×4 (82S129) or 512×4 (82S131), so 256 or 512 words. Ten mux bits
  (5× '153) would allow up to 1K.

### 4.3 Micro-sequencer **[HYP]**
* **U32/U33 ('ALS161)** form the micro-program counter (load and increment).
* **U43–U47 ('153 ×5)** form the **next-address multiplexer**, 10 bits. Each bit
  picks one of four sources:
  1. µPC (continue)
  2. branch field from the pipeline register
  3. dispatch address from the U22/U23 decode PROMs
  4. interrupt/INIT vector from U34/U35/U42
* **U31 ('F151)** is the 8→1 **condition select**. It picks one flag (carry,
  zero, sign, A=B from the FPRM over the backplane, or bus/interrupt status) to decide
  whether a conditional branch is taken.

### 4.4 Instruction dispatch **[HYP]**
* **U24 (Am29823)**: candidate instruction register (up to 9 opcode bits),
  loaded from the data bus through U14/U12/U13.
* **U22/U23 (24-pin PROMs, "DDE…")**: map the opcode to a microcode entry
  address. This is the classic "mapping PROM".

### 4.5 Interrupts and initialisation **[HYP]**
* **U34/U35 ('LS348 ×2, cascaded)** give 16-level priority encoding. They take
  requests from the backplane through U1/U4 (inverting buffers) and latch them
  with U36 ('LS174).
* **U42 INITROM**: the microcode start address at reset, and possibly the trap
  or interrupt microcode vectors.
* **R1/D1/C28**: possibly a power-on reset network.

### 4.6 Backplane interface **[OBS] + [HYP]**
* **[OBS]** U2/U3 ('LS374) have many traces fanning out to the edge fingers.
  These 16 registered outputs are candidates for **ADR0–7 plus the
  bus-control lines** (RD̅, WR̅, and others), registered so that the address
  is stable before the command, as the bus protocol requires.
* U14 ('245) and U12/U13 ('374) tap the data bus, for example to capture the
  instruction word.
* U38 (74F38) and U54 (7438) are open-collector drivers for wired-OR
  backplane lines (for example interrupt acknowledge, ready, bus request).

### 4.7 Clock **[OBS] + [HYP]**
U93 is a tapped delay line, with the CLK jumper picking one of the 40–80 ns
taps. Together with U53 ('F74) and the U63/U64/U73/U74 gates it generates the
microcycle clock and its phases: the pipeline register clock, the RAM write
pulse for the FPRM's 27S07s, and the bus strobes. Changing the tap changes
the CPU timing, so **do not move the jumper**.

---

## 5. FPRM ↔ FPSM interface (backplane P1)

Both cards plug into the 72-pin EZbuss backplane in **adjacent slots**: 13
and 14 in the Synclavier 25-slot bin, or 9 and 10 in the original ABLE bin.
See the [EZbuss table](../../docs/able-reference.md#3-ezbuss-72-pin-two-sided-edge-connector-appendix-ii-table-1).

* **FPSM → FPRM** goes over the *shared* bus. The 8-bit ADR0–7 (pins 15–29
  odd) carries the operation code; RD̅ (11) and WR̅ (9) give direction and
  timing; the FPRM answers on SYN̅ (5); data moves on BDB0–15. The FPRM is
  addressed the same way as any I/O device.
* **FPRM → FPSM** has **three private lines: Z̅ (64), C̅ (62), MIN̅ (60)**,
  wired only between the two CPU slots. That is the documented reason the
  cards must be adjacent.
* There is no system clock line. Timing is generated on the FPSM (delay
  line) and handshaken with SYN̅. Pin 69 carries a 1 MHz reference generated
  on a card; which card drives it is still to be checked. *Cards and
  Components* says the processor runs on a "D3 clock" from the
  MFC/D40Q/M64K/D100 cards.

Owner-supplied notes: the backplane is referred to as "IB25"; peripheral
cards (MFC1, floppy/Winchester controllers) cable out of the rack.

The edge-finger and empty-backplane continuity procedures are in
[`docs/bench-checklist.md`](../../docs/bench-checklist.md). The documented
pin-out in machine-readable form is
[`data/ezbuss-pinout.csv`](../../data/ezbuss-pinout.csv).

### J1 (34-pin ribbon, to other external cards)
* **[OBS]** J1 sits right next to **U91/U92**: two 16-pin DIP resistor
  networks with 8 isolated resistors each. That gives 16 **series-terminated**
  lines, and series termination goes on the *driving* end, so this card drives
  at least 16 signals off-board on the ribbon.
* What it connects to, and which signals it carries (microword fields,
  sequencer state, timing?), is still open.

---

## 6. Verification plan
1. **Archive the seven PROMs.** Lift each label just far enough to read the
   part number, then read the chip. Bipolar PROMs (82S/Am27S/N82HS) read in
   most universal programmers.
2. Record the JP1 delay tap, the solder-side rework resistors, and the
   R1/D1/C28 values.
3. Power pins first (§4.1), then the PROM→pipeline-register buses (SMRxx data
   pins → register D inputs; these should be one-to-one).
4. Microaddress bus: the '153 Y outputs → the A pins of all SMR PROMs and
   INITROM. The '161 Q outputs and the U22/U23 outputs → the '153 inputs.
5. Map the P1 edge fingers on both cards (§5), then J1.
6. With the microcode dumped and the field map known, a disassembler/simulator
   becomes possible. The microword field boundaries come out of steps 3–5.

## 7. Open questions
* The exact PROM types, and therefore the microcode depth and width.
* What U22 is (its label is destroyed), and whether U22/U23 are two halves of
  one wide mapping PROM.
* U4 is read as `74F240`; check it is not a '245. U52 is read as `74F175`;
  U73 as `74F08`.
* The P1 edge pin-out (§5), especially the FPRM↔FPSM lines.
* Which external cards J1 connects to, and what it carries.
* Which chips drive ADR0–7: the '153s or U2/U3.
* How Model C extensions (`RPT n`, the undefined destination codes 270–277)
  are encoded and executed.
* What the handwritten "12-2" means.

The step-by-step checks for whoever has a board are in
[`docs/bench-checklist.md`](../../docs/bench-checklist.md).
