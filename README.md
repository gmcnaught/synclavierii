# Hardware reverse-engineering notes

First-pass schematics and BOMs worked out from board photos. Each folder holds
a `README.md` (layout, inferred netlist, verification plan), a `bom.csv` and a
block-level `schematic-block.svg`.

## NED Synclavier II CPU (two-card set)

| Board | Role | Folder |
|---|---|---|
| FPRM-185 | CPU **Register Module**: 16-bit ALU (4× 74F181 + 74S182), 16×16 register file (4× CY27S07), memory address/data bus interface | [`synclavier-fprm-185/`](synclavier-fprm-185/README.md) |
| FPSM-185 | CPU **Sequencer Module**: ≈28-bit pipelined microcode (SMR00–03), next-address sequencer, opcode dispatch PROMs, interrupt priority, clock delay line | [`synclavier-fpsm-185/`](synclavier-fpsm-185/README.md) |

The two cards talk **through the backplane** (the P1 edge connector on each).
The FPSM drives the FPRM's ALU function, register addresses and latch enables,
and the FPRM returns ALU flags. The 34-pin J1 ribbon on each card goes to
*other* external cards. Mapping the P1 edge fingers on both cards is the most
useful next measurement.

**Installation (owner-supplied):** both cards plug into the system backplane
(for example IB25) in **strictly adjacent slots**, and the sequencer↔register
lines are hard-wired in the backplane. Peripheral cards (MFC1 terminal,
floppy/Winchester controllers) cable out of the rack instead. The cheapest
way to find the private CPU lines is to beep the two CPU slots against each
other and against a peripheral slot on an empty backplane. The procedure is
in [FPSM README §5](synclavier-fpsm-185/README.md#5-fprm--fpsm-interface-backplane-p1).

```
        ABLE backplane (P1 on both cards)
   ═══════╤═══════════════════════════════════╤══════════
          │ addr/data · control fields ◄──────┤ (FPSM → FPRM)
          │ ALU flags / condition ────────────► (FPRM → FPSM)
  ┌───────┴────────┐                  ┌───────┴────────┐
  │   FPRM-185     │                  │   FPSM-185     │
  │ ALU · regs ·   │                  │ microcode ·    │
  │ MAR · data bus │                  │ sequencer · clk│
  └───────┬────────┘                  └───────┬────────┘
          │ J1 34-pin                         │ J1 34-pin
          ▼ to other external cards           ▼ to other external cards
```
