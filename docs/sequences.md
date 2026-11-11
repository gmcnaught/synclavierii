# Demo sequences (Music Notation test material)

NED shipped one demo sequence, the Liszt "Choeur des Fileuses" excerpt
(`W0 Demo Files/*SQ0DATA.sseq` in NED's source tree; `.SQ1DATA`–`.SQ7DATA`
there are empty 512-sector slots). To test SYN-5.3's Music Notation
Display (Main Menu K) and its hardcopy with real multi-part music,
`tools/seq_record.py` records public-domain pieces into SYN-5.3's memory
recorder in the simulator, one part per track, and saves them as
`.SQnDATA` through SYN-5.3's own save path. `tools/timbre_disk.py --seq`
puts them on a W1: sub-catalog. Tags: **[OBS]** seen in source, binary or
simulator, **[INF]** inferred, **[UNK]** open.

## 1. How the panel records and saves a sequence [OBS]

| Step | Panel (VPK button name) | NED source |
|---|---|---|
| Keyboard timbre | BANK n, ENTRY m (`bankb`, `timb.n-1`, `entryb`, `timb.m-1`) | `05-BUTT/175-PRF5` |
| Arm a track | its track button (`trak.i`): solos it and, while not recording, sets `RECD.TRK` | `05-BUTT/174-PRF4` `TOGGLE.TRACK.SOLO.STATE` |
| Record | RECORD (`record`) starts the sequencer and recording on `RECD.TRK`; with no track armed it picks a track that has the keyboard timbre, else an empty one | `05-BUTT/173-PRF3` `PROCESS.RECORD.BUTTON`, `04-SEQ/163-SEQ3` `START.RECORD` |
| Stop | STOP (`stop`) | `173-PRF3` |
| Save | hold ENTRY WRITE (`entrywrt`), SEQUENCE (`seqb`), button n (`timb.n`): "n SECTORS WRITTEN TO DISK" | `175-PRF5` `SEQUENCER.RECALL.BUTTON` (`IF (ENTRY.WRITE\BANK.WRITE)`: `NAH.COLLECT`, `WRITE.SEQUENCE`) |
| Recall | SEQUENCE, button n: `.SQnDATA` from the current catalog, then the system catalog | same |

The save writes only over an existing `.SQnDATA` of enough sectors
(error 6 otherwise), so `seq_record.py` adds empty 512-sector slots to a
temporary copy of W0, as NED's W0 had them.

Track button 1 is absolute track 2 (tracks 0 and 1 are the keyboard's).
Each note is a 2- or 4-word record (`SYNLITS/SYNCLITS`): word 1 bit 0 =
4-word record, bits 1–10 the time since the previous note (ms), bits 11–14
the duration's high bits and a power-of-4 exponent; word 2 the duration's
low 10 bits and the key number (MIDI note − 36). `seq_record.py show`
lists them.

## 2. Timing and the notation grid [OBS]

* The click rate (ms per beat) is set with CLICK and the knob (the knob
  moves the value at a rate that grows with its distance from centre,
  `06-MAIN/395-UPDT`); the display shows beats per minute with two
  decimals. It is saved in the file (word 13, `SEQ.CLICK`) and restored
  on recall (`03-PRIM/131-SDF2`).
* Sequence time 50 ms (`ZERO.TIME`) is beat 1. In the simulator the
  recorder starts about 60 ms after the RECORD press, so beat b is played
  110 ms + b × click after it. Keys are scanned every 5 ms.
* Music Notation places notes on a grid of `SAMP.CLICK.RATE` ms per
  click (`MNOTMOD/REFRFNCS.xpl REFRESH_INITIALIZE`), or of a live click
  track when one is in use, and rounds starts and lengths to the staff's
  resolution (Res, default 16 = sixteenths).

## 3. Tempo, metre and key [OBS]

* **Tempo:** SYN-5.3 sequences can hold a tempo map and a meter map
  (`SEQ.MAP.PTRS`, `SYNLITS/THDLITS`; `03-PRIM/041-MAPS`, `042-METR`;
  CLICK + START inserts a tempo event, CLICK + SPEED + START a meter
  event, `173-PRF3`). The Music Notation Display reads neither: its grid
  is the click rate or a live click track (`MNOTMOD/GLOBFNCS.xpl
  CONVERT_TIME`).
* **Metre, key, clef:** TimeSig, Key, Clf and Res are settings of the
  Music Notation screen, held in an external-memory sector the module
  allocates at start-up (`MNOTMOD/MNOTSOU.xpl` `MENU_BASE`,
  `GLOBFNCS.xpl INITIALIZE.SEQED`: 4/4, key C, treble clef, Res 16). One
  TimeSig for the whole screen, one key per staff, none of it in the
  `.SQnDATA` file.

So one sequence cannot show a change of metre or key in Music Notation.
The Brahms excerpt is two sequences, one per section, each with its own
click rate (the tempo), and Music Notation is set to that section's
TimeSig and key.

## 4. The pieces

| Slot | Piece | Tracks | Click | Music Notation settings | Source and licence |
|---|---|---|---|---|---|
| SQ0 | Liszt, "Choeur des Fileuses" (NED's demo) | as NED made it | 500 ms | — | NED's `W0 Demo Files/*SQ0DATA.sseq` (supply it yourself; not in this repository) |
| SQ1 | J. S. Bach, chorale "Aus meines Herzens Grunde", BWV 269 (repeat not taken) | 4: S, A, T, B | 750 ms | 4 staves, 3/4, key G, clefs G G F F | Mutopia Project piece 378, [`bwv_269.mid`](https://www.mutopiaproject.org/ftp/BachJS/BWV269/bwv_269/bwv_269.mid), **Public Domain** |
| SQ2 | Minuet in G, BWV Anh. 114 (repeats not taken) | 2: right hand, left hand | 500 ms | 2 staves, 3/4, key G, clefs G F | Mutopia Project piece 75, [`anna-magdalena-04.mid`](https://www.mutopiaproject.org/ftp/BachJS/BWVAnh114/anna-magdalena-04/anna-magdalena-04.mid), **Public Domain** |
| SQ3 | Brahms, String Quartet No. 2 in A minor, Op. 51 No. 2, III, Quasi Minuetto, moderato, bars 16–39 | 4: Vn 1, Vn 2, Va, Vc | 526 ms (♩ = 114) | 4 staves, 3/4, key C (A minor), clefs G G A F | OpenScore String Quartets, [`sq7302602.mxl`](https://github.com/OpenScore/StringQuartets/tree/main/scores/Brahms%2C_Johannes/String_Quartet_No.2%2C_Op.51_No.2), **CC0 1.0** (credit requested: OpenScore String Quartets, <https://musescore.com/openscore-string-quartets>) |
| SQ4 | the same, Allegretto vivace, bars 40–55 | 4 | 429 ms (♩ = 140) | 4 staves, 2/4, key A, clefs G G A F | as SQ3 |

The note lists are in [`data/sequences/`](../data/sequences/) (each names
its source, licence and how it was converted). The Bach files are
`seq_record.py convert` output of the Mutopia MIDI files: BWV 269's MIDI
file has one track per staff, so `--split 1,2` separates soprano/alto and
tenor/bass (a note where both voices end together is taken as a unison),
and `--shift 2` puts the upbeat on beat 3 of an empty first bar. The
Brahms files come from the MusicXML file (notes, ties merged; grace notes,
dynamics and articulation left out; triplets kept, which Music Notation
rounds to its resolution). Only these encodings were used, no editions
under copyright.

## 5. Making the disk

```bash
W0=W0-53.IMG     # tools/w0_image.py output (has W0:.NEWDATA; SIMPLE FM SINE = BANK 1 ENTRY 2)
for p in 1:bach-bwv269-chorale 2:bach-bwv-anh114-minuet 3:brahms-op51-2-iii-minuetto 4:brahms-op51-2-iii-allegretto; do
  python3 tools/seq_record.py record data/sequences/${p#*:}.txt --w0 $W0 --slot ${p%%:*} --sseq ${p#*:}.sseq
done
python3 tools/timbre_disk.py W1-DEMOS.IMG --seq "DEMOS:0=*SQ0DATA.sseq" \
    --seq DEMOS:1=bach-bwv269-chorale.sseq --seq DEMOS:2=bach-bwv-anh114-minuet.sseq \
    --seq DEMOS:3=brahms-op51-2-iii-minuetto.sseq --seq DEMOS:4=brahms-op51-2-iii-allegretto.sseq
python3 tools/timbre_disk.py W1.IMG timbres/*.stmb --seq DEMOS:1=...   # or with timbre libraries
```

Recording runs in simulated real time (about twice that on a current PC:
the chorale, 4 × 49 s, takes about 8 minutes). Each `record` prints a
check of the saved file against the note list. In SYN-5.3: D (Subcatalog
Directory), `W1:DEMOS`, RETURN, then SEQUENCE + 1 … 4 recalls a piece,
START plays it, K shows it (set Staves, TimeSig, Key and Clf as in the
table). `seq_record.py view` does the same in the simulator and saves the
Music Notation screens as PNG:

```bash
python3 tools/seq_record.py view --w0 W0-53.IMG --w1 W1-DEMOS.IMG --catalog W1:DEMOS --slot 1 \
    --piece data/sequences/bach-bwv269-chorale.txt --pages 3 --play 5 --png chorale [--print chorale.prn]
```

## 6. Verification

Simulator, 2026-11-11 (W0 = `tools/w0_image.py` output, VT640 + mouse,
32 FM voices, timbre BANK 1 ENTRY 2 "SIMPLE FM SINE") [OBS]:

| Slot | Saved | Notes per track | Worst start / length error vs the note list | Playback, FM register writes in 5 s (idle: 2000) |
|---|---|---|---|---|
| SQ0 Liszt (NED's file) | — | 113, 118, 177, 35 | — | 3127 (the piece starts at 2 s) |
| SQ1 chorale | 16 sectors | 46, 58, 59, 60 | 10 ms / 30 ms | 4793 |
| SQ2 minuet | 11 sectors | 129, 75 | 7 ms / 27 ms | 4986 |
| SQ3 minuetto | 16 sectors | 99, 93, 89, 85 | 13 ms / 29 ms | 7810 |
| SQ4 allegretto | 16 sectors | 101, 79, 103, 73 | 15 ms / 27 ms | 16062 |

* Every note of every part is in the saved file (`record`'s check: none
  missing, none extra). Lengths are 25–30 ms short because each key goes
  up 25 ms before the note's end (so repeated notes re-strike); both are
  far below the notation grid (a sixteenth is 107–188 ms here).
* From a W1: image made with `timbre_disk.py --seq` (SQ0–SQ4 in
  `W1:DEMOS`), with W0: holding no sequences: D, `W1:DEMOS`, RETURN, then
  SEQUENCE + n recalls each one, START plays it, and Music Notation shows
  the expected staves: the chorale's four voices with the upbeat in bar 1,
  3/4 and G major; the minuet's two hands (left-hand chord G-B-D in bar
  1); the Brahms minuetto in 3/4 with alto clef for the viola and the
  cello's octaves (its triplets drawn as the nearest sixteenths); the
  Allegretto vivace in 2/4, A major, with the tie across the first bar
  line and the sixteenth-note runs.
* Hardcopy: H on the chorale's first screen sent 36,500 bytes to the
  printer port; `tools/print_render.py --raw` renders the same picture as
  the screen.
* `tests/test_seq_record.py` with `SYNCLAVIER_W0` set records a two-part
  piece and checks the saved file (passes; about 90 s).

Two terminal details found on the way [OBS, simulator]:

* ESC on the Main Menu makes SYN-5.3 take the next key as part of an
  escape sequence: ESC then K does not open Music Notation. After the
  Subcatalog Directory's RETURN no ESC is needed (it is already back on
  the Main Menu).
* As soon as the Music Notation cursor moves into a staff's menu (Trk,
  Key, Clf, Res), the status box shows "Measure# 65535, TimeSig 0/0,
  Click 0/0, Pitch C1, Duration 0/0", as after a hardcopy
  ([`devices/d40-printer.md`](devices/d40-printer.md) §3.2); bar lines
  and notes stay right, and entering a Measure# redraws the box correctly.
  [UNK] whether a real instrument does the same (the core runs the same
  code, so it should agree with the simulator).

## 7. Open questions [UNK]

* Not yet tried on the MiSTer (needs a VT640 state image with W1:, the
  W1-DEMOS image in S4).
* A tempo change inside one sequence (tempo map, CLICK + START) and
  whether Music Notation's grid then follows it; a live click track
  (CLICK.TRACK.MODE ≥ 4) would make Music Notation follow a recorded
  tempo, which could carry the Brahms tempo change in one sequence (the
  metre and key change would still need two screens).
* The beats-per-measure setting (`SEQ.BPM`, 4 by default) is left as it
  is; it changes the panel's beat display, not Music Notation.
