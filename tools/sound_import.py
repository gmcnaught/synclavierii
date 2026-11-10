#!/usr/bin/env python3
"""Import WAV/AIFF audio into NED Synclavier sound files (catalog type 5) in
a NED disk image, and export sound files back to WAV.

    sound_import.py DISK.IMG IN.wav [--name NAME] [--subcat PATH] [--replace]
                    [--rate HZ] [--pitch HZ] [--caption TEXT] [--create MB]
    sound_import.py DISK.IMG --export PATH OUT.wav

The sound file is what SYN-5.3 creates for a new recording
(STMMOD/STEDSOU:113-240, STRECSOU:1034-1077) and what its loader reads
(docs/poly-synth.md section 5):

  sector 0     header: compat 4, data type 1 (raw sampled data), valid and
               total data length, DATA.END and MARK.END (time of the last
               sample frame), MARK.START 0, hertz (base pitch x 10), octave,
               period index (30 MHz ticks), Nyquist, 4 symbols, loop
               (TOTAL.LENGTH/LOOP.LENGTH in words), stereo flag, sample
               rate (kHz x 10), file handle (the name), caption
  sectors 1-2  symbol table: ORIGIN 0, # 0, $ and END at DATA.END
  sectors 3..  16-bit two's-complement samples; stereo files interleave
               left (even word) and right (odd word), as CLARA4 does

Input: WAV (PCM 8/16/24/32-bit integer, 32/64-bit float, WAVE_FORMAT_
EXTENSIBLE) or AIFF/AIFF-C (PCM 8-32 bit, 'NONE'/'sowt'); 1 or 2 channels.
Samples wider than 16 bits are rounded to 16 bits (no dither).
Loop: the first loop of a WAV `smpl` chunk (end inclusive) or the AIFF
INST sustain loop (MARK positions, end exclusive). Pitch: `smpl` unity
note + fraction or INST base note + detune, else A 440 (hertz 4400, as
SYN-5.3 creates files; the file then plays at its own rate on key A).

Sample rate: NED stores it in kHz x 10, i.e. 100 Hz steps, from 0.1 to
100 kHz (STDRSOUD:388-408). A rate that is not a multiple of 100 Hz (22050,
11025) or above 100 kHz is resampled (windowed sinc) to the next multiple
of 100 Hz up (100 kHz at most); --rate HZ resamples to HZ instead.

--name: 1-8 characters A-Z 0-9 . - (default: the input's stem, upper
case, cut to 8). --subcat: put it in that type-6/7 sub-catalog. --replace:
overwrite a file of the same name (in place when it fits). --create MB:
make DISK.IMG as an empty disk of MB MB first (a blank W1:).

Treat input files as untrusted data: only the chunks listed are read.
"""
import argparse
import math
import os
import re
import struct
import sys
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools.ned_disk import SECTOR_WORDS, add_file, blank_disk, load_bytes, read_file  # noqa: E402

SOUND_FILE_TYPE = 5

# header words (SYNLITS/SAMPLITS:117-151)
SF_COMPATIBILITY = 0
SF_FILE_DATA_TYPE = 1
SF_VALID_DATA = 2          # sector msb, sector, word (words, both channels)
SF_TOTAL_DATA = 6          # 0, sectors, 0
SF_DATA_END = 9            # s, ms, us of the last sample frame
SF_KEYBOARD_DECAY = 12
SF_HERTZ = 18              # base pitch x 10
SF_OCTAVE = 19             # 2 words, floating point octave.semitones
SF_PERIOD_INDEX = 21       # 30 MHz ticks per sample
SF_NYQUIST = 22            # Hz
SF_MARK_START = 23
SF_MARK_END = 26
SF_CURSOR_TIME = 29
SF_GAIN_EXPONENT = 32
SF_NUMBER_OF_SYMBOLS = 33
SF_TOTAL_LENGTH = 34       # loop end (exclusive), words: msb, sector, word
SF_LOOP_LENGTH = 37        # loop length, words
SF_MAGIC_NUMBER = 40
SF_STEREO = 41
SF_SAMPLE_RATE = 42        # kHz x 10
SF_FILE_HANDLE = 53        # C string, 64 words
SF_FILE_HANDLE_WL = 64
SF_ID_FIELD_BYTES = 127    # caption byte count
SF_ID_FIELD = 128          # caption
SYMBOL_LENGTH = 8
MAX_SYMBOLS = 64
DATA_SECTOR = 3            # data from file sector 3 (197-PAL1:556-568)
MAX_SECTORS = 65535        # files of 65536 sectors or more are refused (197-PAL1:378-386)

OCTAVE_A = (0o61341, 0o43702)  # FLOATING POINT 3.09 (STEDSOU:176, 197-PAL:1043)


class Audio:
    """rate (Hz), chans (list of lists of 16-bit ints, 1 or 2), loop
    (start frame, end frame exclusive) or None, pitch (Hz) or None."""

    def __init__(self, rate, chans, loop=None, pitch=None):
        self.rate, self.chans, self.loop, self.pitch = rate, chans, loop, pitch

    @property
    def frames(self):
        return len(self.chans[0])


# ------------------------------------------------------------------ input
def _to16(v, bits):
    """A signed sample of `bits` bits to 16 bits, rounded, clamped."""
    if bits == 16:
        return v
    if bits < 16:
        return v << (16 - bits)
    s = bits - 16
    return max(-32768, min(32767, (v + (1 << (s - 1))) >> s))


def _float16(x):
    return max(-32768, min(32767, int(math.floor(x * 32768.0 + 0.5))))


def _decode(raw, nch, bits, fmt, big):
    """Interleaved PCM bytes -> per-channel lists of 16-bit ints. fmt:
    'int' or 'float'. Samples are left-justified in whole bytes (WAV and
    AIFF), so the container width decides; 8-bit WAV is unsigned."""
    width = (bits + 7) // 8
    if nch < 1 or width < 1:
        raise ValueError("bad sample format")
    n = len(raw) // (width * nch)
    raw = raw[:n * nch * width]
    out = []
    if fmt == "float":
        if width not in (4, 8):
            raise ValueError("%d-bit float samples" % bits)
        vals = struct.unpack("%s%d%s" % (">" if big else "<", n * nch, "f" if width == 4 else "d"), raw)
        out = [_float16(v) for v in vals]
    elif width == 1:
        out = [((b - 128) if not big else (b - 256 if b & 0x80 else b)) << 8 for b in raw]
    elif width == 2:
        out = list(struct.unpack("%s%dh" % (">" if big else "<", n * nch), raw))
    elif width in (3, 4):
        order = "big" if big else "little"
        out = [_to16(int.from_bytes(raw[k:k + width], order, signed=True), 8 * width)
               for k in range(0, len(raw), width)]
    else:
        raise ValueError("%d-bit samples" % bits)
    return [out[c::nch] for c in range(nch)]


def _chunks(data, start, big):
    p = start
    while p + 8 <= len(data):
        cid = data[p:p + 4]
        size = struct.unpack(">I" if big else "<I", data[p + 4:p + 8])[0]
        yield cid, data[p + 8:p + 8 + size]
        p += 8 + size + (size & 1)


def read_wav(data):
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF WAVE file")
    fmt = raw = smpl = None
    for cid, body in _chunks(data, 12, False):
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            raw = body
        elif cid == b"smpl":
            smpl = body
    if fmt is None or raw is None:
        raise ValueError("WAV without fmt or data chunk")
    tag, nch, rate, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 40:
        tag = struct.unpack("<H", fmt[24:26])[0]
    if tag not in (1, 3):
        raise ValueError("WAV format %d: only PCM and IEEE float" % tag)
    chans = _decode(raw, nch, bits, "float" if tag == 3 else "int", False)
    loop = pitch = None
    if smpl and len(smpl) >= 36:
        note, frac = struct.unpack("<II", smpl[12:20])
        nloops = struct.unpack("<I", smpl[28:32])[0]
        if note or frac:
            pitch = 440.0 * 2 ** ((note + frac / 2 ** 32 - 69) / 12)
        if nloops and len(smpl) >= 60:
            _, _, start, end, _, _ = struct.unpack("<6I", smpl[36:60])
            loop = (start, end + 1)
    return Audio(rate, chans, loop, pitch)


def _ext80(b):
    """IEEE 754 80-bit extended (AIFF sample rate) -> float."""
    exp = ((b[0] & 0x7F) << 8) | b[1]
    mant = int.from_bytes(b[2:10], "big")
    if exp == 0 and mant == 0:
        return 0.0
    v = mant * 2.0 ** (exp - 16383 - 63)
    return -v if b[0] & 0x80 else v


def read_aiff(data):
    if data[:4] != b"FORM" or data[8:12] not in (b"AIFF", b"AIFC"):
        raise ValueError("not an AIFF file")
    comm = ssnd = mark = inst = None
    for cid, body in _chunks(data, 12, True):
        if cid == b"COMM":
            comm = body
        elif cid == b"SSND":
            ssnd = body
        elif cid == b"MARK":
            mark = body
        elif cid == b"INST":
            inst = body
    if comm is None or ssnd is None:
        raise ValueError("AIFF without COMM or SSND chunk")
    nch, nframes, bits = struct.unpack(">hIh", comm[:8])
    rate = _ext80(comm[8:18])
    big = True
    if data[8:12] == b"AIFC":
        comp = comm[18:22]
        if comp == b"sowt":
            big = False
        elif comp not in (b"NONE", b"twos"):
            raise ValueError("AIFF-C compression %r: only uncompressed PCM" % comp)
    off = struct.unpack(">I", ssnd[:4])[0]
    raw = ssnd[8 + off:8 + off + nframes * nch * ((bits + 7) // 8)]
    chans = _decode(raw, nch, bits, "int", big)
    loop = pitch = None
    if inst and len(inst) >= 20:
        base, detune = struct.unpack(">Bb", inst[0:2])
        pitch = 440.0 * 2 ** ((base + detune / 100.0 - 69) / 12)
        mode, b_id, e_id = struct.unpack(">hhh", inst[8:14])
        marks = {}
        if mark:
            n = struct.unpack(">H", mark[:2])[0]
            p = 2
            for _ in range(n):
                mid, pos, ln = struct.unpack(">hIB", mark[p:p + 7])
                marks[mid] = pos
                p += 7 + ln + ((ln + 1) & 1)          # pstring padded to even
        if mode and b_id in marks and e_id in marks and marks[e_id] > marks[b_id]:
            loop = (marks[b_id], marks[e_id])
    return Audio(int(round(rate)), chans, loop, pitch)


def read_audio(path):
    data = open(path, "rb").read()
    if data[:4] == b"RIFF":
        a = read_wav(data)
    elif data[:4] == b"FORM":
        a = read_aiff(data)
    else:
        raise ValueError("%s: not WAV or AIFF" % path)
    if len(a.chans) not in (1, 2):
        raise ValueError("%d channels: NED sound files are mono or stereo" % len(a.chans))
    if not a.frames:
        raise ValueError("no samples")
    return a


# -------------------------------------------------------------- resampling
def resample(chans, rate_in, rate_out, taps=24):
    """Windowed-sinc (Blackman) resampling of 16-bit channels."""
    ratio = Fraction(rate_out, rate_in)
    n_in = len(chans[0])
    n_out = int(n_in * ratio)
    cutoff = min(1.0, float(ratio))           # low-pass below the lower Nyquist
    step = Fraction(rate_in, rate_out)
    out = []
    for ch in chans:
        o = []
        for k in range(n_out):
            t = k * step
            c = t.numerator // t.denominator
            f = float(t - c)
            acc = 0.0
            for i in range(c - taps + 1, c + taps + 1):
                if 0 <= i < n_in:
                    x = (i - c - f) * cutoff
                    w = i - c - f
                    win = 0.42 + 0.5 * math.cos(math.pi * w / taps) + 0.08 * math.cos(2 * math.pi * w / taps)
                    acc += ch[i] * cutoff * (math.sin(math.pi * x) / (math.pi * x) if x else 1.0) * win
            o.append(max(-32768, min(32767, int(math.floor(acc + 0.5)))))
        out.append(o)
    return out


def ned_rate(rate):
    """The rate NED can store for `rate` Hz: next multiple of 100 Hz up,
    within 100 Hz .. 100 kHz."""
    return max(100, min(100_000, -(-rate // 100) * 100))


# ------------------------------------------------------- NED time arithmetic
def _ratio(num, den):
    """RATIOMULTIPLY's num/den: integer + 48 fraction bits, truncated
    (MATHSOU:340-352)."""
    return (num << 48) // den


def _ratio_multiply(x, num, den):
    """(x * num/den) as MULTIPLY returns it: (truncated, rounded, fraction
    word a2) (MATHSOU:240-322)."""
    full = x * _ratio(num, den)
    trunc = full >> 48
    a2 = (full >> 32) & 0xFFFF
    return trunc, trunc + (a2 >> 15), a2


def index_to_time(frame, khz10):
    """Sample frame index -> (s, ms, us) as INDEX_TO_TIME (194-SAMP:123-162)."""
    ms, _, a2 = _ratio_multiply(frame, 10, khz10)          # then UNROUND
    s, ms = divmod(ms, 1000)
    p = 1000 * a2
    us = (p >> 16) + ((p >> 15) & 1)
    if us == 1000:
        us, ms = 0, ms + 1
        if ms == 1000:
            ms, s = 0, s + 1
    return s, ms, us


def time_to_index(s, ms, us, khz10):
    """(s, ms, us) -> sample frame index as TIME_TO_INDEX (194-SAMP:15-48),
    before the stereo doubling."""
    return _ratio_multiply(s * 1000 + ms, khz10, 10)[1] + _ratio_multiply(us, khz10, 10000)[1]


def end_time(frame, khz10):
    """The time to store for frame `frame`: INDEX_TO_TIME's, or the next
    microsecond up when TIME_TO_INDEX (whose kHz/10 ratio is truncated, so
    a product ending in exactly .5 rounds down, e.g. 5 ms at 44.1 kHz)
    would read it back one frame early [CHOICE: SYN-5.3 writes
    INDEX_TO_TIME's value; the loader then plays one frame less]."""
    s, ms, us = index_to_time(frame, khz10)
    for _ in range(4):
        if time_to_index(s, ms, us, khz10) >= frame:
            break
        us += 1
        if us == 1000:
            us, ms = 0, ms + 1
            if ms == 1000:
                ms, s = 0, s + 1
    return s, ms, us


def _sec_word(words):
    """A word count as (sector msb, sector, word)."""
    return [words >> 24, (words >> 8) & 0xFFFF, words & 0xFF]


# ------------------------------------------------------------ the sound file
def float_octave(v):
    """NED floating point (2 words) of v > 0 [INF from the one constant
    in the source, 3.09 = 061341 043702: word 0 = sign + mantissa bits 1-15,
    word 1 = mantissa bits 16-23 << 8 | 0300 + exponent, mantissa in
    [0.5, 1), truncated]."""
    if v <= 0:
        return 0, 0
    m, e = math.frexp(v)
    bits = int(m * (1 << 23))
    return bits >> 8, (bits & 0xFF) << 8 | (0o300 + e) & 0xFF


def octave_of(hertz10):
    """octave.semitones as the SFM shows a pitch (A 440 = 3.09) [INF]."""
    key = 45 + 12 * math.log2(hertz10 / 4400.0)
    k = int(math.floor(key + 0.5))
    if k < 0:
        return 0.0
    cents = (key - k) * 100
    return k // 12 + (k % 12 + cents / 100.0) / 100.0


def _pack_string(text, nwords):
    b = text.encode("latin-1")[:2 * nwords]
    b += bytes(2 * nwords - len(b))
    return [b[k] | b[k + 1] << 8 for k in range(0, 2 * nwords, 2)]


def _symbol(t, name):
    """Symbol table entry: time (3 words), name length, 4 words of name
    padded with blanks (as in the W0 sound files)."""
    return list(t) + [len(name)] + _pack_string(name.ljust(8), 4)


def check_name(name):
    if not re.fullmatch(r"[A-Z0-9.\-]{1,8}", name):
        raise ValueError("name %r: 1-8 characters A-Z 0-9 . -" % name)
    return name


def default_name(path):
    stem = os.path.splitext(os.path.basename(path))[0].upper()
    return re.sub(r"[^A-Z0-9.\-]", "", stem)[:8] or "SOUND"


def build_sound_file(chans, rate, name, loop=None, pitch=None, caption=""):
    """Words of a type-5 sound file: 16-bit channels (1 or 2 lists) at
    `rate` Hz (a multiple of 100), loop = (start, end exclusive) frames,
    pitch in Hz (None: A 440)."""
    if rate % 100 or not 100 <= rate <= 100_000:
        raise ValueError("rate %d Hz: NED stores multiples of 100 Hz, 0.1-100 kHz" % rate)
    check_name(name)
    stereo = len(chans) == 2
    nframes = len(chans[0])
    khz10 = rate // 100
    nwords = nframes * len(chans)
    sectors = -(-nwords // SECTOR_WORDS)
    if DATA_SECTOR + sectors > MAX_SECTORS:
        raise ValueError("%d sectors: SYN-5.3 loads files under 65536 sectors" % (DATA_SECTOR + sectors))
    hertz10 = 4400 if pitch is None else int(math.floor(pitch * 10 + 0.5))
    if not 1 <= hertz10 <= 0xFFFF:
        raise ValueError("pitch %.1f Hz out of range" % pitch)
    h = [0] * SECTOR_WORDS
    h[SF_COMPATIBILITY] = 4
    h[SF_FILE_DATA_TYPE] = 1                       # raw sampled data
    h[SF_VALID_DATA:SF_VALID_DATA + 3] = _sec_word(nwords)
    h[SF_TOTAL_DATA:SF_TOTAL_DATA + 3] = [0, sectors, 0]
    end = end_time(nframes - 1, khz10)
    h[SF_DATA_END:SF_DATA_END + 3] = end
    h[SF_HERTZ] = hertz10
    h[SF_OCTAVE:SF_OCTAVE + 2] = OCTAVE_A if hertz10 == 4400 else float_octave(octave_of(hertz10))
    h[SF_PERIOD_INDEX] = 300_000 // khz10
    h[SF_NYQUIST] = khz10 * 50
    h[SF_MARK_END:SF_MARK_END + 3] = end
    h[SF_NUMBER_OF_SYMBOLS] = 4
    if loop is not None:
        start, stop = loop
        if not 0 <= start < stop <= nframes:
            raise ValueError("loop %d-%d outside 0-%d" % (start, stop, nframes))
        h[SF_TOTAL_LENGTH:SF_TOTAL_LENGTH + 3] = _sec_word(stop * len(chans))
        h[SF_LOOP_LENGTH:SF_LOOP_LENGTH + 3] = _sec_word((stop - start) * len(chans))
    h[SF_STEREO] = int(stereo)
    h[SF_SAMPLE_RATE] = khz10
    h[SF_FILE_HANDLE:SF_FILE_HANDLE + 4] = _pack_string(name, 4)
    if caption:
        cap = caption.encode("latin-1", "replace")[:256]
        h[SF_ID_FIELD_BYTES] = len(cap)
        h[SF_ID_FIELD:] = _pack_string(cap.decode("latin-1"), SECTOR_WORDS - SF_ID_FIELD)
    sym = (_symbol((0, 0, 0), "ORIGIN") + _symbol((0, 0, 0), "#") + _symbol(end, "$")
           + _symbol(end, "END"))
    sym += [0] * (2 * SECTOR_WORDS - len(sym))
    if stereo:
        data = [0] * nwords
        data[0::2], data[1::2] = chans
    else:
        data = list(chans[0])
    data = [v & 0xFFFF for v in data] + [0] * (sectors * SECTOR_WORDS - nwords)
    return h + sym + data


def parse_sound_file(words):
    """Header fields and channels (signed 16-bit lists) of a sound file's
    words, by the valid data length."""
    h = list(words[:SECTOR_WORDS])
    stereo = h[SF_STEREO] == 1
    nwords = (h[SF_VALID_DATA] << 24) + (h[SF_VALID_DATA + 1] << 8) + h[SF_VALID_DATA + 2]
    raw = words[DATA_SECTOR * SECTOR_WORDS:DATA_SECTOR * SECTOR_WORDS + nwords]
    raw = [v - 0x10000 if v & 0x8000 else v for v in raw]
    chans = [raw[0::2], raw[1::2]] if stereo else [raw]
    nch = len(chans)
    khz10 = h[SF_SAMPLE_RATE] or int(round(300_000 / (h[SF_PERIOD_INDEX] or 600)))
    loop = None
    tl = (h[SF_TOTAL_LENGTH + 1] << 8) + h[SF_TOTAL_LENGTH + 2]
    ll = (h[SF_LOOP_LENGTH + 1] << 8) + h[SF_LOOP_LENGTH + 2]
    if tl and ll:
        loop = ((tl - ll) // nch, tl // nch)
    hz = h[SF_HERTZ] / 10.0 if h[SF_HERTZ] else 440.0
    name = bytes(b for w in h[SF_FILE_HANDLE:SF_FILE_HANDLE + SF_FILE_HANDLE_WL]
                 for b in (w & 0xFF, w >> 8)).split(b"\0")[0].decode("latin-1")
    n = min(h[SF_ID_FIELD_BYTES], 256)
    caption = bytes(b for w in h[SF_ID_FIELD:] for b in (w & 0xFF, w >> 8))[:n].decode("latin-1")
    return {"header": h, "symbols": list(words[SECTOR_WORDS:3 * SECTOR_WORDS]), "rate": khz10 * 100,
            "chans": chans, "loop": loop, "pitch": hz, "name": name, "caption": caption}


def wav_bytes(chans, rate, loop=None, pitch=None):
    """16-bit PCM WAV with a `smpl` chunk (unity note, loop) when pitch or
    loop is given."""
    nch, n = len(chans), len(chans[0])
    inter = [chans[c][k] for k in range(n) for c in range(nch)]
    data = struct.pack("<%dh" % len(inter), *inter)
    fmt = struct.pack("<HHIIHH", 1, nch, rate, rate * nch * 2, nch * 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data + (b"\0" if len(data) & 1 else b"")
    if pitch is not None or loop is not None:
        note = 69 + 12 * math.log2((pitch or 440.0) / 440.0)
        unity = int(math.floor(note))
        frac = int(round((note - unity) * 2 ** 32)) & 0xFFFFFFFF
        loops = struct.pack("<6I", 0, 0, loop[0], loop[1] - 1, 0, 0) if loop else b""
        smpl = struct.pack("<9I", 0, 0, int(round(1e9 / rate)), unity, frac, 0, 0,
                           1 if loop else 0, 0) + loops
        body += b"smpl" + struct.pack("<I", len(smpl)) + smpl
    return b"RIFF" + struct.pack("<I", len(body)) + body


def export_wav(words, path):
    """Write the sound file `words` as a 16-bit WAV at `path`; returns the
    parsed fields (parse_sound_file)."""
    f = parse_sound_file(words)
    open(path, "wb").write(wav_bytes(f["chans"], f["rate"], f["loop"], f["pitch"]))
    return f


def sound_file_from_audio(audio, name, rate=None, caption=""):
    """Sound file words for an Audio; resampled to `rate` (default: the
    input rate when NED can store it, else ned_rate)."""
    target = rate or ned_rate(audio.rate)
    chans, loop = audio.chans, audio.loop
    if target != audio.rate:
        chans = resample(chans, audio.rate, target)
        if loop:
            r = Fraction(target, audio.rate)
            loop = (int(loop[0] * r), min(len(chans[0]), int(loop[1] * r)))
    return build_sound_file(chans, target, name, loop, audio.pitch, caption)


def import_sound(disk, audio_path, name=None, subcat=None, replace=False, rate=None, pitch=None,
                 caption=""):
    """Import WAV/AIFF `audio_path` into hard-disk image bytes `disk` (a
    bytearray, changed in place) as sound file `name`; returns (path in the
    catalog, start sector, words)."""
    audio = read_audio(audio_path)
    if pitch is not None:
        audio.pitch = pitch
    name = check_name(name or default_name(audio_path))
    words = sound_file_from_audio(audio, name, rate, caption)
    path = (subcat.strip("/") + "/" if subcat else "") + name
    data = struct.pack(">%dH" % len(words), *words)
    start = add_file(disk, path, data, SOUND_FILE_TYPE, replace=replace)
    return path, start, words


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("disk")
    ap.add_argument("audio", nargs="?")
    ap.add_argument("--name")
    ap.add_argument("--subcat")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--rate", type=int, help="resample to this rate (Hz, a multiple of 100)")
    ap.add_argument("--pitch", type=float, help="base pitch in Hz (default: from the file, else 440)")
    ap.add_argument("--caption", default="")
    ap.add_argument("--create", type=int, metavar="MB", help="create DISK as an empty disk first")
    ap.add_argument("--export", nargs=2, metavar=("PATH", "OUT"), help="write sound file PATH as WAV")
    a = ap.parse_args(argv)
    if a.export:
        W = load_bytes(open(a.disk, "rb").read())
        f = export_wav(read_file(W, a.export[0]), a.export[1])
        print("%s: %s, %d Hz, %d frames%s -> %s" % (
            a.export[0], "stereo" if len(f["chans"]) == 2 else "mono", f["rate"], len(f["chans"][0]),
            ", loop %d-%d" % f["loop"] if f["loop"] else "", a.export[1]))
        return 0
    if not a.audio:
        ap.error("IN.wav required (or --export)")
    if a.create:
        if os.path.exists(a.disk):
            ap.error("%s exists (--create makes a new disk)" % a.disk)
        disk = blank_disk(a.create)
    else:
        disk = bytearray(open(a.disk, "rb").read())
    path, start, words = import_sound(disk, a.audio, a.name, a.subcat, a.replace, a.rate, a.pitch,
                                      a.caption)
    open(a.disk, "wb").write(disk)
    f = parse_sound_file(words)
    print("%s: %s, %d Hz, %d frames%s, %d sectors at %d" % (
        path, "stereo" if len(f["chans"]) == 2 else "mono", f["rate"], len(f["chans"][0]),
        ", loop %d-%d" % f["loop"] if f["loop"] else "", -(-len(words) // SECTOR_WORDS), start))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
