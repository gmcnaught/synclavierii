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


## `print_render.py`: printer capture to pages

```bash
python3 tools/print_render.py CAPTURE OUT.png [--pdf OUT.pdf] [--raw]
python3 tools/print_render.py --blank FILE [--mb 4]
```

Renders what the Synclavier printed on its D40 printer port (the core's
capture file from SD slot S6, or with `--raw` the bytes alone, e.g.
`sim/devices/printer.py Printer.out`) as an IDS Paper Tiger / Prism would:
text at 10.5 cpi and 6 lpi, ETX graphics (7-dot columns, 84 dpi), form
feeds as new pages; one PNG per page and optionally one PDF. `--blank`
makes an empty capture file to mount in S6. Format and printer model:
[`docs/devices/d40-printer.md`](../docs/devices/d40-printer.md). Standard
library only.

---

Results of running the disassembler on NED's runtime packages are in
[`docs/model-c-runtime-analysis.md`](../docs/model-c-runtime-analysis.md).

## `stm_source.py`: digital sample-to-memory source (M18)

```bash
python3 tools/stm_source.py IN.wav OUT.STM [--start S] [--seconds S]
python3 tools/stm_source.py --info OUT.STM
```

Converts a PCM WAV (1 or 2 channels, 8/16/24/32-bit; deeper samples keep
their top 16 bits) into the file the core reads from SD slot S5 when
SYN-5.3 records with its digital STM input: a 512-byte header (`SYNCSTM1`,
channels, rate in 100 Hz units, frames) and the samples as big-endian
words. Format and behaviour: [`docs/devices/digital-stm.md`](../docs/devices/digital-stm.md).
Standard library only.

## `music_printing.py`: NED Music Printing from source

```bash
python3 tools/music_printing.py build ~/src/jbemond-Software mp   # XPL compiler + *SPLT-7
python3 tools/music_printing.py install W0-53.IMG mp              # into W0:.SYSTEM
```

Builds NED's XPL compiler (clang++, macOS) and NED's Music Printing
program as NED's release build does, with the printer handshake off and
the VT640 Screen display starting at pixel 8, and installs it on a W0 image (`docs/devices/d40-printer.md` §3.4). Nothing it
builds is committed.

## `stmb.py`, `timbre_disk.py`: timbre libraries

```bash
python3 tools/stmb.py convert "LIBRARY FOLDER" -o LIB.stmb        # NED FM library text -> .NEWDATA
python3 tools/timbre_disk.py W1-TIMBRES.IMG LIB1.stmb LIB2.stmb   # a W1: with one sub-catalog per library
python3 tools/timbre_disk.py W1.IMG --seq DEMOS:1=chorale.sseq     # sequences as W1:DEMOS/.SQnDATA
python3 tools/timbre_disk.py W1.IMG FM/*.stmb --samples Original-NED-Sample-Patch-Libraries  # + sampled libraries
python3 tools/sample_library.py Original-NED-Sample-Patch-Libraries [--all-sounds]     # list what --samples adds
```

`sample_library.py` packs the NED sample/patch banks into 18 libraries by
instrument family and copies each `.caf` back to the NED sound file it
was exported from (`SNCL` chunk + samples). See `docs/timbre-libraries.md`.

## `seq_record.py`: demo sequences

```bash
python3 tools/seq_record.py record PIECE.txt|.mid --w0 W0-53.IMG --slot 1 --sseq OUT.sseq
python3 tools/seq_record.py view --w0 W0-53.IMG --w1 W1.IMG --catalog W1:DEMOS --slot 1 --piece PIECE.txt --png OUT
python3 tools/seq_record.py show OUT.sseq                         # header and notes of a sequence file
python3 tools/seq_record.py convert IN.mid OUT.txt [--split 1,2] [--shift BEATS]
```

Records a piece (Standard MIDI File or note list; one part per track) in
the simulator through SYN-5.3's panel (RECORD, timed keys, STOP) and saves
it with ENTRY WRITE + SEQUENCE + n, then copies `.SQnDATA` out. The pieces
in `data/sequences/` are public domain or CC0. See `docs/sequences.md`.

