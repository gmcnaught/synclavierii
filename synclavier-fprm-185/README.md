# NED Synclavier II — Board FPRM-185: first-pass schematic & BOM

> **Status: first pass from photos only.** Everything here was worked out from
> two 822×622 px photos (component side + solder side, studiorepair.com). The
> part identification is reliable. The **netlist mostly is not.** Where a
> connection follows from how a standard part has to be wired (for example,
> '181 ALU slices with a '182 carry generator), it is shown as *standard
> topology*. Every other connection is a **hypothesis** to check against the
> real board with a meter.

Files:

| File | Contents |
|---|---|
| [`bom.csv`](bom.csv) | Bill of materials with a confidence rating for each line |
| [`schematic-block.svg`](schematic-block.svg) | Block-level schematic of the inferred data and control paths |
| `README.md` | This document: board layout, inferred netlist, open questions, how to verify |

---

## 1. Board overview

* **Board:** New England Digital Corp. **FPRM-185** (silkscreen on both sides;
  solder side also shows `NED FPRM-185` and UL mark `94V-1`).
* **Construction:** 2-layer through-hole PCB, all DIP logic, one gold card-edge
  connector (right) and one blue shrouded IDC header (left, J1).
* **Logic family:** almost all Fairchild **74F** FAST TTL (date codes 8641–8747),
  plus one TI 74ALS244, one TI 74S182 and four Cypress CY27S07 bipolar RAMs.
  The board was built around 1987–88; the U28 label says ©1986.
* **Programmed parts:** **U18** (16-pin) and **U28** (20-pin, label
  `FPRM 01 ©1986 N.E.D.`) sit in sockets and carry paper labels, so they are
  factory-programmed PROMs or PALs. **Read both into a programmer and archive
  the contents before doing anything else to the board.** No public dumps are
  known.
* **Rework:** a blue jumper wire (W1) on the solder side near U11/U12. Record
  both ends; it may be a revision fix that a schematic redraw has to include.

### What the board does

**FPRM-185 is the Register Module of the Synclavier's CPU** (the ABLE
processor). The CPU is built on two cards:

| Card | Role |
|---|---|
| **FPRM-185, Register Module** (this board) | Data path: ALU, general registers, memory address/data interface |
| **[FPSM-185, Sequencer Module](../synclavier-fpsm-185/README.md)** (partner card) | Control: instruction fetch/decode, microcode sequencing, timing |

*(Card roles supplied by the board owner. The block-level reading below follows
from them plus the parts on the board.)*

The data path on this card:

* **ALU:** four 74F181 4-bit slices plus a 74S182 carry look-ahead make a
  **16-bit ALU**.
* **Register file:** four 16×4 CY27S07 RAMs make a **16-word × 16-bit**
  register file. On a Register Module this is most likely the CPU's general
  registers (plus any internal scratch registers) rather than a co-processor
  scratchpad.
* **Bus interface:** two '245s for the 16-bit data bus, and two '373s (U5/U6)
  whose 16 traces run straight to the edge fingers. Those two latches are most
  likely the **memory address register** driving the backplane address bus.
* **Pipeline registers:** '373/'374 latches around the ALU and register file.
* **Local programmed logic:** U18 and U28, socketed. Now that sequencing is
  known to live on the FPSM, these are more likely local decode/steering logic
  than the main microcode store. The 20-pin U28 could be a PAL, for example.
* **Control link to the FPSM: over the backplane (P1).** *(Confirmed by the
  board owner: the two CPU cards talk through the backplane, not the ribbon.
  They must sit in strictly adjacent slots, for example in the IB25
  backplane.)*
  The FPSM's microword control fields (ALU function S0–S3/M/Cn, register-file
  address and write enable, latch and output enables) must reach this card
  through edge fingers. Status (carry, zero, sign, A=B) and possibly opcode
  bits go back the same way. Candidates on this card for receiving them are
  U7 ('ALS244 buffer), then U2 ('139) and U18/U28 (local decode).
* **J1 (34-pin ribbon) goes to other external cards, not to the FPSM.**
  Which cards, and what it carries, is still open. Its traces run into the
  '181/'182 ALU area, so it may extend the data path or flags off-card.

---

## 2. Physical layout (component side, connector on the right)

The reference designators follow a column/row grid, `U<column><row>`, with
column 1 next to the card edge:

```
 col 5 (J1 side)     col 4               col 3            col 2            col 1 (edge side)
 U41 74S182          U31 CY27S07         U21 74F00        U11 74F10        U1 74F153
 U43 74F181 (24p)    U33 CY27S07         U23 74F04        U12 74F374       U2 74F139      C1 6.8µF
 U44 74F181 (24p)    U34 74F373          U24 74F374       U13 74F374       U3 74F245
 U46 74F181 (24p)    U35 74F373          U25 74F373       U14 74F374       U4 74F245      P1
 U48 74F181 (24p)    U36 74F373          U26 74F373       U15 74F373       U5 74F373  ──► edge
                     U37 CY27S07         U27 74F373       U16 74F373       U6 74F373  ──► edge
 J1 34-pin IDC       U38 CY27S07         U28 PROM/PAL*    U17 74F374       U7 74ALS244
                                                          U18 PROM*        U8 74F112
                                                         (* socketed, labelled)
```

Gaps in the numbering (U22, U32, U42, U45, U47) are where the 24-pin '181s
take up two grid slots, or where a slot is left empty.

---

## 3. Bill of materials (summary)

The full BOM, with notes and a confidence rating per line, is in [`bom.csv`](bom.csv).

| Qty | Part | Function | RefDes |
|---:|---|---|---|
| 4 | 74F181 | 4-bit ALU (DIP-24, 0.6") | U43, U44, U46, U48 |
| 1 | 74S182 | Carry look-ahead (TI) | U41 |
| 4 | CY27S07 | 16×4 bipolar RAM, 3-state | U31, U33, U37, U38 |
| 10 | 74F373 | Octal transparent latch | U5, U6, U15, U16, U25, U26, U27, U34, U35, U36 |
| 5 | 74F374 | Octal D-FF register | U12, U13, U14, U17, U24 |
| 2 | 74F245 | Octal bus transceiver | U3, U4 |
| 1 | 74ALS244 | Octal buffer (TI) | U7 |
| 1 | 74F139 | Dual 2→4 decoder | U2 |
| 1 | 74F153 | Dual 4→1 mux | U1 |
| 1 | 74F112 | Dual JK flip-flop | U8 |
| 1 | 74F10 | Triple 3-input NAND | U11 |
| 1 | 74F00 | Quad 2-input NAND | U21 |
| 1 | 74F04 | Hex inverter | U23 |
| 1 | PROM, 16-pin (82S129/82S123 class?) | Local decode | U18 (socketed) |
| 1 | PROM or PAL, 20-pin (82S135 / PAL16xx?) | `FPRM 01` | U28 (socketed) |
| 1 | 6.8 µF tantalum, axial | +5 V bulk | C1 |
| ~30 | Dipped capacitor, probably 0.1 µF | Decoupling | C2–C36 |
| 8 | Resistor, value TBD | Pull-up / termination | R1–R8 |
| 1 | 34-pin (2×17) shrouded IDC header | Ribbon to other external cards (not the FPSM) | J1 |
| 1 | Card-edge, ~38 fingers per side (estimated) | Backplane | P1 |

**Total: 35 ICs** (33 logic/RAM plus 2 programmed parts).

---

## 4. Inferred netlist

Confidence key: **[STD]** = standard topology, very likely · **[OBS]** = seen
in the photo (traces visible) · **[HYP]** = hypothesis.

### 4.1 Power **[STD]**

Every IC uses the normal TTL power pins. Use these to check orientation and to
find the +5 V and GND fingers on P1:

| Package | Parts | VCC | GND |
|---|---|---|---|
| DIP-14 | F00, F04, F10 | 14 | 7 |
| DIP-16 | F112, F139, F153, S182, 27S07 | 16 | 8 |
| DIP-20 | F245, F373, F374, ALS244 | 20 | 10 |
| DIP-24 | F181 | 24 | 12 |

C1 (6.8 µF, polarised) sits at the top of the edge connector, between +5 V and
GND where power enters. One dipped capacitor sits next to almost every IC.

### 4.2 16-bit ALU: U43/U44/U46/U48 + U41 **[STD]**

A '182 with four '181s is almost always wired this way. Which '181 is the
least-significant slice still needs checking (the physical order suggests
U48 = LS … U43 = MS, or the reverse):

| From | Pin | To | Pin | Net |
|---|---|---|---|---|
| Slice 0 '181 | P̅ (15) | U41 '182 | P̅0 (4) | P0 |
| Slice 0 '181 | G̅ (17) | U41 | G̅0 (3) | G0 |
| Slice 1 '181 | P̅ (15) | U41 | P̅1 (2) | P1 |
| Slice 1 '181 | G̅ (17) | U41 | G̅1 (1) | G1 |
| Slice 2 '181 | P̅ (15) | U41 | P̅2 (15) | P2 |
| Slice 2 '181 | G̅ (17) | U41 | G̅2 (14) | G2 |
| Slice 3 '181 | P̅ (15) | U41 | P̅3 (6) | P3 |
| Slice 3 '181 | G̅ (17) | U41 | G̅3 (5) | G3 |
| Carry-in source | — | Slice 0 Cn (7) **and** U41 Cn (13) | — | CIN |
| U41 | Cn+x (12) | Slice 1 '181 | Cn (7) | C4 |
| U41 | Cn+y (11) | Slice 2 '181 | Cn (7) | C8 |
| U41 | Cn+z (9) | Slice 3 '181 | Cn (7) | C12 |
| Slice 3 '181 | Cn+4 (16) | flag logic / status mux | — | COUT **[HYP]** |
| All four '181 | A=B (14), open collector | wired-AND, one pull-up R | — | ZERO **[HYP]** (R8 is a candidate, it sits between U44 and U46) |
| All four '181 | S0–S3 (6,5,4,3), M (8) | bussed together | — | ALU function, from the control PROM / pipeline register **[HYP]** |

'181 operand pins (repeated on each slice): A0–A3 = 2, 23, 21, 19;
B0–B3 = 1, 22, 20, 18; F0–F3 = 9, 10, 11, 13.

### 4.3 Register file: U31/U33/U37/U38 (CY27S07, 16×4) **[STD] + [HYP]**

* **[STD]** The address pins A0–A3 (1, 15, 14, 13) and the write enable WE̅ (3)
  are bussed to all four RAMs, which gives one 16×16 file. CS̅ (2) is common or
  tied low.
* **[STD]** Each RAM's data inputs D1–D4 (4, 6, 10, 12) and outputs O1–O4
  (5, 7, 9, 11) cover one nibble.
* **[HYP]** The outputs go to the U34–U36 '373 latches, which feed the '181
  A/B inputs. The data inputs come from the ALU result latches or the internal
  bus. The address A0–A3 comes from the FPSM over the backplane (register fields of the
  instruction or microinstruction), possibly through a local '374 or '153.
* Check against the CY27S07 datasheet whether the outputs are inverting
  (some 27S0x/'189 parts are). Inverted outputs would explain a '181 used in
  active-low mode.

### 4.4 Backplane (memory / I/O bus) interface (column 1) **[OBS] + [HYP]**

* **[OBS]** U5 and U6 ('373): one bank of 8 traces runs from each part
  straight to the edge fingers, 16 lines in total. Because this is the CPU
  data-path card, these are most likely the **memory address register**,
  latched from the ALU or internal bus and driving the 16-bit address bus.
* **[HYP]** U3/U4 ('245) connect the 16-bit backplane **data bus** to the
  internal data bus (IDB). DIR and G̅ come from the read/write and enable
  signals of the current bus cycle (from the FPSM).
* **[HYP]** U7 ('ALS244) buffers incoming backplane control lines. These now
  most likely include the **FPSM's control fields and clock**, as well as
  reset and wait/ready.
* **[HYP]** U2 ('139) decodes control fields into individual enables:
  register load strobes and output enables for the result latches.
* **[HYP]** U1 ('153) is a condition/status multiplexer. It selects which
  flag (carry, zero, sign, A=B …) goes over the backplane to the FPSM's
  U31 ('151) condition select for conditional branching.
* **[HYP]** U8 ('112) holds CPU flag bits, for example the carry/link
  flip-flop, updated from the '181 Cn+4 output.

### 4.5 Data-path control (columns 2–3) **[HYP]**

* Control comes **from the FPSM sequencer over the backplane (P1)**.
  U18/U28 do local decoding of those fields, for example
  turning a compact field into several latch/output enables, or forming the
  register-file address and write pulse.
* U17 ('374) is a candidate **instruction register**: it would capture the
  fetched instruction word from the data bus and send opcode/register fields
  to the FPSM and the register-file address lines. Alternatively it is a
  local pipeline register for control fields.
* U12–U14 and U24 ('374) are operand and pipeline registers. U15/U16 and
  U25–U27 ('373) are ALU-result latches that read back onto the IDB.
* U11/U21/U23 provide the glue logic: clock buffering and inversion, strobe
  gating, and write-pulse shaping for the 27S07s.

### 4.6 Connectors

* **P1 card edge:** about 38 fingers per side (estimated from the photo; count
  on the real board). The pin-out is unknown. Start by finding the +5 V and GND
  fingers with a meter against the VCC/GND pins in §4.1, then follow the 16 data
  lines from U3/U4 and the 16 lines from U5/U6.
  **The P1 pin-out is now the key unknown**, because the FPRM↔FPSM control
  and status lines run through it. See the [FPSM README §5](../synclavier-fpsm-185/README.md#5-fprm--fpsm-interface-backplane-p1) for the edge-finger
  table to fill in for both cards.
* **J1 2×17 IDC:** about 17 rows visible, so 34 pins (to be confirmed). The
  ribbon goes to **other external cards, not the FPSM**. Its destination and
  signals are still to be identified.

---

## 5. Verification plan (to turn this into a real schematic)

1. **Archive U18 and U28.** Identify the chip under each label, then read it
   (an 82S-series PROM reads directly; a PAL may be secured and need
   brute-force or jedutil-style recovery).
2. **Take high-resolution photos.** Shoot both sides square-on at 600 dpi or
   better, lit evenly and at the same scale. Mirror the solder side and overlay
   it on the component side; the traces can then be followed in an image
   editor or in KiCad's image-to-footprint workflow.
3. **Power first.** Beep VCC/GND (table in §4.1) to the edge fingers to find
   the power pins.
4. **Do the certain nets first.** Confirm the '181/'182 wiring in §4.2. It
   fixes the bit ordering of the ALU slices, which then fixes the bit ordering
   of everything downstream.
5. **Follow buses as groups.** For each '373/'374/'245, beep its 8 outputs
   against the 8 inputs of the likely neighbours. Buses on this board run as
   parallel groups of traces, so one confirmed bit usually gives the other
   seven.
6. **Control nets.** Trace the latch enables (pin 11), output enables (pin 1),
   '181 S/M/Cn and RAM A0–A3/WE̅ back to the edge fingers (via U7), U17/U18/U28
   and the glue gates. A P1 finger-to-function table is the most useful single
   result, because it documents the FPRM↔FPSM interface.
7. **Record W1** and the resistor values (measure them; the colour bands can't
   be read in the photos).
8. **Capture in KiCad.** Use one hierarchical sheet each for the backplane interface,
   control, register file and ALU, using the RefDes from `bom.csv`.

## 6. Open questions

* The P1 edge pin-out, which carries the FPRM↔FPSM control interface.
* Which external cards J1 connects to, and what it carries.
* Is U17 the instruction register, and are U5/U6 the memory address register?
* Which ABLE model this CPU implements, and how the 16 register-file words
  map to its architectural registers.
* U18/U28: exact part numbers and contents.
* U41 marking: read as `SN74S182N` with medium confidence (photo blur).
* U8 marking: read as `74F112`; check that it is not a '109/'113.
* The exact number of capacitors, and the P1/J1 pin counts.
