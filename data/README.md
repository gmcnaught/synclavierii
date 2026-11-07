# Machine-readable data

| File | Contents | Status |
|---|---|---|
| [`ezbuss-pinout.csv`](ezbuss-pinout.csv) | 72-pin EZbuss edge pinout, transcribed from the ABLE HW Reference Manual (App. II, Table 1). Columns for the expected chip on each card and empty `*_measured` columns to fill in at the bench. | Documented (ABLE bin). Not yet checked on the 185 cards. |
| [`able-opcodes.csv`](able-opcodes.csv) | Every source and destination code range, with operation, flag effects and manual page. | Documented. Mnemonics are suggestions, not NED's. |
| [`netlist.csv`](netlist.csv) | Known and hypothesised connections on both boards. `tag` = STD (standard topology) / OBS (seen in photo) / HYP (hypothesis), or combinations. | Inferred. Update as you measure. |

Conventions: pin numbers are IC or edge-connector pins; `'181 slice S0…S3`
names an ALU slice whose RefDes order is not yet known. Signals are named
without overbars, and the active-low ones are flagged in the pinout file.
