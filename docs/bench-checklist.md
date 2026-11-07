# Bench checklist (for whoever has the hardware)

Everything that can only be learned from a physical FPRM-185, FPSM-185 or
Synclavier bin, in priority order. Record the results in this repo:

* CSVs under `data/`
* PROM images under `roms/` (with checksums)
* photos as links (or committed, if you own them)

Use the tags in the board READMEs: **[STD]** standard topology, **[OBS]**
seen in a photo, **[HYP]** hypothesis.

> ⚠️ Treat these as irreplaceable. There are no public dumps or schematics.
> Work with the bin unpowered unless a step says otherwise. Use an
> anti-static strap. Note the orientation of every socketed part before
> pulling it.

---

## 0. Before touching anything

- [ ] Photograph each card as found: both sides, labels readable, jumper
      positions visible.
- [ ] Record bin type, slot numbers, card revisions and anything handwritten
      (the FPSM has "12-2" on it).
- [ ] Record which slot each card is in. Expected: FPRM in 13, FPSM or DSM in
      14, core memory in 11–12.

## 1. Read and archive the PROMs (highest value)

| Card | RefDes | Label | Pins | Suspected type | Notes |
|---|---|---|---|---|---|
| FPSM | U61 | SMR00 | 24 | 8-bit bipolar PROM (1K×8 / 2K×8?) | microcode bits 0–7 |
| FPSM | U71 | SMR01 | 24 | as U61 | microcode bits 8–15 |
| FPSM | U81 | SMR02 | 24 | as U61 | microcode bits 16–23 |
| FPSM | U51 | SMR03 | 16 | 82S129 (256×4) / 82S131 (512×4)? | microcode bits 24–27 |
| FPSM | U22 | label destroyed ("REV B"?) | 24 | 8-bit PROM | instruction decode / dispatch |
| FPSM | U23 | DDE…2 | 24 | 8-bit PROM | instruction decode / dispatch |
| FPSM | U42 | INITROM | 16 | 82S123 (32×8) / 82S129? | reset / trap vectors |
| FPRM | U18 | (partly legible, ©1986) | 16 | 82S123 (32×8)? | IAB class decode **[HYP]** |
| FPRM | U28 | FPRM 01 ©1986 N.E.D. | 20 | 82S135 (256×8) **or PAL16xx** | IAB decode / steering |

- [ ] Lift each label only far enough to read the chip marking, and
      photograph it.
- [ ] Read each part **twice** and compare the checksums. Bipolar PROMs
      (82S/N82HS/Am27S/MMI 63S) read in most universal programmers.
- [ ] If U28 is a PAL and reads as secured, record that and don't
      brute-force it on the original. Note the part number and fuse map type.
- [ ] Save the images as `roms/<card>-<refdes>-<label>.bin`, with SHA-256 in
      `roms/SHA256SUMS`.
- [ ] If possible, also dump the DSM's PROMs (Model D) and the FPSM PROMs from
      a second card, to check revisions.

## 2. Settings and rework

- [ ] FPSM **JP1 delay-line tap**: which of 40/50/60/70/80 is linked to CLK.
      Do not change it.
- [ ] FPSM U93 delay line: the full marking.
- [ ] FPSM solder-side rework: two resistors near U36–U38. Values and both
      ends.
- [ ] FPSM R1, D1, C28: values.
- [ ] FPRM **W1** blue jumper (solder side, near U11/U12): both ends.
- [ ] FPRM R1–R8 values (meter, out of circuit if needed).
- [ ] FPSM U91/U92 resistor-network marking and value.
- [ ] Confirm the uncertain chip markings: FPRM U41 ('S182?), U8 ('F112?);
      FPSM U4 ('F240?), U52 ('F175?), U73 ('F08?).

## 3. Edge connector (each card, out of the bin, unpowered)

Number the fingers 1–72 per the EZbuss convention: odd numbers on one side,
even on the other, with 1/2 = GND and 71/72 = +5 V. Fill in
[`data/ezbuss-pinout.csv`](../data/ezbuss-pinout.csv) columns
`fprm_measured` / `fpsm_measured`.

IC power pins, for reference:

| Package | VCC | GND |
|---|---|---|
| DIP-14 | 14 | 7 |
| DIP-16 | 16 | 8 |
| DIP-20 | 20 | 10 |
| DIP-24 (F181, Am29823) | 24 | 12 |

- [ ] **Power first:** confirm GND (1, 2, 14, 31, 48) and +5 V (71, 72)
      against the IC power pins above.

- [ ] **Flags:** pins 60 (MIN̅), 62 (C̅) and 64 (Z̅) should reach the flag
      logic on the FPRM (U8/U1?) and the condition mux on the FPSM (U31).
- [ ] **ADR0–7** (odd pins 15–29): on the FPRM they should reach U7; on the
      FPSM, find the driver (U2/U3 or the '153s).
- [ ] **RD̅ 11, WR̅ 9, SYN̅ 5, HALT̅ 6, HAK̅ 4, IRQ̅ 3, ACK̅ 13, IORST̅/INIT̅
      7/8.**
- [ ] **BDB0–15** (odd pins 63–33) → FPRM U3/U4, FPSM U14.
- [ ] **MA0–15** (even pins 46–16) → FPRM U5/U6.
- [ ] Note any finger that is used but doesn't match the table.

## 4. Backplane (bin empty, unpowered)

Quick way to find the private CPU lines. Use the FPRM slot *S_RM* (13), the
FPSM slot *S_SM* (14) and one peripheral slot *S_X*. For every contact in
*S_RM*:

| Result | Meaning |
|---|---|
| Same position in *S_SM* **and** *S_X* | bussed line |
| Only *S_SM*, same position | **private CPU link** |
| Only *S_SM*, different position | **private CPU link, crossed**: record both |
| Nothing | unused, or local to that slot |

- [ ] Record slot numbers used and the backplane part number (for example
      "IB25"). Repeat between slots 11–12 and 13–14 to see how MA0–15 is
      routed. The ABLE table limits MA to slots 1–12.
- [ ] Note any terminator networks (the table's pull-up values: 330 Ω on BDB
      and MA, 1 k ×3 on ADR, and so on).

## 5. Photos for trace work

- [ ] Both sides of each card, **≥ 600 dpi**, square-on, even lighting, no
      flash glare, same scale, with a ruler in frame.
- [ ] A close-up of each chip marking.
- [ ] With these, most traces can be followed by mirroring and overlaying the
      solder side.

## 6. J1 ribbons (CPU cards)

- [ ] Where does each CPU card's J1 cable go? Note the destination card,
      connector and cable length.
- [ ] On the FPSM: which U91/U92 resistor each J1 pin passes through, and
      which chip drives it.
- [ ] On the FPRM: which chip pins each J1 pin reaches.

## 7. Powered checks (only on a known-good system)

- [ ] Logic-probe or scope SYN̅, RD̅, WR̅ and ADR0–7 while the system idles.
      This confirms the bus cycle and the delay from address to command
      (about 180 ns on the ABLE/80).
- [ ] Note the microcycle clock frequency on the FPSM (after U93/U53).
- [ ] If a HOP (D01) card is available, single-step instructions from
      [`instruction-set.md` §10](instruction-set.md#10-worked-examples) and
      record the bus activity. Especially the Model C items: `IM(n) TO D10`
      (repeat), the `SBB` borrow convention, and whether **relative** or
      **untaken** transfers change D10 (the link register).
      [`model-c-runtime-analysis.md`](model-c-runtime-analysis.md) settles the
      rest from NED's code.
- [ ] Probe FPSM U32/U33 ('ALS161) during a `RPT`: do they load *n* and
      count down?
