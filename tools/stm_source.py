#!/usr/bin/env python3
"""Make a digital sample-to-memory source (M18) from a WAV file: the file
the core reads from SD slot S5 when SYN-5.3 records on its STM screen with
the digital input (docs/devices/digital-stm.md).

    stm_source.py IN.wav OUT.STM [--seconds S] [--start S]
    stm_source.py --info FILE.STM

Input: PCM WAV, 1 or 2 channels, 8, 16, 24 or 32 bits. Samples become
16-bit words: 16-bit samples as they are; deeper ones keep their top 16
bits (no dither); 8-bit ones (unsigned) are shifted up [CHOICE]. The rate
is kept in Hz and as SYN-5.3's unit, 100 Hz (kHz x 10, e.g. 44100 -> 441);
SYN-5.3 accepts typed digital rates of 40.0-50.5 kHz, so other rates are
reported (the file still works: SYN-5.3 records at whatever rate the input
reports).

Output (sim/devices/digstm.py Source.to_bytes): a 512-byte header block
(big-endian words: "SYNCSTM1", version 1, channels, rate in 100 Hz units,
frames (32 bits), rate in Hz (32 bits)), then the samples as big-endian
words, left/right interleaved, padded with zeros to whole 512-byte blocks.
At most 65535 data blocks (16.7M words: 5.8 min mono or 2.9 min stereo at
48 kHz); longer input is cut (SYN-5.3 records at most 32 MB per sound file
anyway).
"""
import os
import struct
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sim.devices.digstm import MAX_BLOCKS, Source  # noqa: E402


def read_wav(path, start=0.0, seconds=None):
    """(samples, channels, rate_hz) of a PCM WAV: signed 16-bit ints,
    interleaved."""
    with wave.open(path, "rb") as w:
        ch, width, hz, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if ch not in (1, 2):
            raise ValueError("%s: %d channels (1 or 2 only)" % (path, ch))
        first = min(n, int(round(start * hz)))
        w.setpos(first)
        count = n - first if seconds is None else min(n - first, int(round(seconds * hz)))
        raw = w.readframes(count)
    vals = []
    if width == 1:
        vals = [(b - 128) << 8 for b in raw]
    elif width == 2:
        vals = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    elif width in (3, 4):
        for i in range(0, len(raw) - width + 1, width):
            vals.append(struct.unpack_from("<h", raw, i + width - 2)[0])
    else:
        raise ValueError("%s: %d-byte samples" % (path, width))
    return vals, ch, hz


def make_source(samples, ch, hz):
    """A Source, cut to what the core addresses (MAX_BLOCKS data blocks)."""
    limit = MAX_BLOCKS * 256 // ch
    frames = min(len(samples) // ch, limit)
    return Source(samples[:frames * ch], ch, max(1, min(1023, round(hz / 100))), hz)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", help="WAV file (or, with --info, an .STM file)")
    ap.add_argument("output", nargs="?", help="the .STM file to write")
    ap.add_argument("--start", type=float, default=0.0, help="skip this many seconds of the WAV")
    ap.add_argument("--seconds", type=float, help="take at most this many seconds")
    ap.add_argument("--info", action="store_true", help="describe an .STM file")
    a = ap.parse_args(argv)
    if a.info:
        s = Source.from_file(a.input)
        print("%s: %s, %d frames (%.2f s) at %d Hz (SYN-5.3 rate %.1f kHz)" % (
            a.input, "stereo" if s.channels == 2 else "mono", s.frames,
            s.frames / s.rate_hz if s.rate_hz else 0, s.rate_hz, s.rate / 10))
        return 0
    if not a.output:
        ap.error("an output file is needed")
    samples, ch, hz = read_wav(a.input, a.start, a.seconds)
    total = len(samples) // ch
    src = make_source(samples, ch, hz)
    open(a.output, "wb").write(src.to_bytes())
    print("%s: %s, %d frames (%.2f s), %d Hz -> rate %.1f kHz" % (
        a.output, "stereo" if ch == 2 else "mono", src.frames, src.frames / hz, hz, src.rate / 10))
    if src.frames < total:
        print("  cut from %d frames (at most %d data blocks)" % (total, MAX_BLOCKS))
    if src.rate * 100 != hz:
        print("  note: %d Hz is not a multiple of 100 Hz; the core paces the input at %d Hz"
              % (hz, src.rate * 100))
    if not 400 <= src.rate <= 505:
        print("  note: SYN-5.3 accepts typed digital rates of 40.0-50.5 kHz only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
