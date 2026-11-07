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
