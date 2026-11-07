# Tools

## `able_disasm.py`: ABLE disassembler

Decodes ABLE 16-bit words into NED assembler syntax (`SOURCE TO
DESTINATION`), using the official NED mnemonics and the Model C extensions
(`MR12D`, `ADC`/`SBB`, `D10`). See [`docs/instruction-set.md`](../docs/instruction-set.md).
Python 3, standard library only.

```bash
python3 tools/able_disasm.py FILE [--model B|C|D] [--start OCT] [--count N] [--base OCT]
python3 tools/able_disasm.py --validate LISTING [--model B]
```

* `FILE`: raw big-endian 16-bit words, such as NED `.sdat` runtime packages or
  memory images. Addresses and immediates are printed in **octal**, as NED
  writes them.
* Heuristics: the word after a `PCI` source is shown as `DATA`; relative
  jumps show their target (`; -> addr`); PCW/PSW, `RPT` (D10) and Model C+
  instructions are annotated.
* `--model B` disables the Model C `MR12D` alias.
* `--validate` compares the decoder against a NED assembler listing.

**Validation:** against NED's own listing `tests/fixtures/NED-SCSI.LST`, 541
of 541 instruction words and 78 of 78 relative-jump targets match. Run
`python3 tests/test_able_disasm.py`.

Results of running it on NED's runtime packages are in
[`docs/model-c-runtime-analysis.md`](../docs/model-c-runtime-analysis.md).
