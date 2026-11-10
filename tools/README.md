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

## `ned_disk.py`: NED disk-image lister and extractor

```bash
python3 tools/ned_disk.py IMAGE                   # list catalogs recursively
python3 tools/ned_disk.py IMAGE --extract OUTDIR  # extract files (exact word length)
python3 tools/ned_disk.py IMAGE --floppy 03-SYSTD 03-SYSTD.IMG  # one floppy, for the MiSTer core
```

Reads NED ABLE/Synclavier `.simg` images (256-word sectors, big-endian
words, nested 8-word catalog entries). The format is described in
[`docs/release-l-image.md`](../docs/release-l-image.md). Output names are
sanitised and confined to OUTDIR. Standard library only.

## `sound_import.py`: WAV/AIFF → NED sound files

```bash
python3 tools/sound_import.py W1.IMG piano.wav --create 32     # new blank 32 MB disk
python3 tools/sound_import.py W1.IMG loop.aif --name LOOP1 [--subcat SUB] [--replace]
python3 tools/sound_import.py W1.IMG --export LOOP1 out.wav     # sound file -> WAV
```

Writes a catalog type-5 sound file as SYN-5.3 creates one (header,
2-sector symbol table, 16-bit samples; stereo interleaved left/right) into
the root catalog or a sub-catalog of a NED hard-disk image; format and
evidence in [`docs/poly-synth.md`](../docs/poly-synth.md) §5.1. Input: WAV
(8/16/24/32-bit PCM, float) or AIFF/AIFF-C, mono or stereo; loop from the
WAV `smpl` chunk or the AIFF sustain loop, base pitch from the unity note
(default A 440, so the file plays at its own rate on key A). Rates that
are not a multiple of 100 Hz (22050, 11025) or above 100 kHz are
resampled; `--rate HZ` resamples to HZ. `--name` defaults to the input's
stem (8 characters, A-Z 0-9 . -). `--export` writes a WAV with a `smpl`
chunk; export then import gives the same file. `ned_disk.add_file` and
`ned_disk.blank_disk` are the catalog helpers. Tests:
`python3 tests/test_sound_import.py` (with `SYNCLAVIER_W0_RAW` = the raw
`W0 Disk Image.simg`, also CLARA3/CLARA4 round trips).

---

Results of running the disassembler on NED's runtime packages are in
[`docs/model-c-runtime-analysis.md`](../docs/model-c-runtime-analysis.md).
