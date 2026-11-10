#!/usr/bin/env python3
"""tools/sound_import.py: WAV/AIFF -> NED sound files (catalog type 5) and
back (M17; format in docs/poly-synth.md section 5).

With SYNCLAVIER_W0_RAW naming Synclavier3's raw "W0 Disk Image.simg" (not
redistributable), also: W0:CLARA3 (mono) and W0:CLARA4 (stereo) exported to
WAV and imported again give the original samples and header, except the
words listed in test_w0_sound_files_round_trip.

Run:  python3 tests/test_sound_import.py
"""
import math
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import sound_import as si  # noqa: E402
from tools.ned_disk import SECTOR_WORDS, blank_disk, load_bytes, read_file, walk  # noqa: E402


def _wav(chans, rate, bits=16, fmt=1, smpl=None):
    nch, n = len(chans), len(chans[0])
    width = bits // 8
    if fmt == 3:
        raw = struct.pack("<%d%s" % (n * nch, "f" if bits == 32 else "d"),
                          *[chans[c][k] for k in range(n) for c in range(nch)])
    elif bits == 8:
        raw = bytes(chans[c][k] + 128 for k in range(n) for c in range(nch))
    else:
        raw = b"".join(chans[c][k].to_bytes(width, "little", signed=True)
                       for k in range(n) for c in range(nch))
    f = struct.pack("<HHIIHH", fmt, nch, rate, rate * nch * width, nch * width, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(f)) + f
    body += b"data" + struct.pack("<I", len(raw)) + raw + (b"\0" if len(raw) & 1 else b"")
    if smpl:
        note, loop = smpl
        s = struct.pack("<9I", 0, 0, 0, note, 0, 0, 0, 1 if loop else 0, 0)
        if loop:
            s += struct.pack("<6I", 0, 0, loop[0], loop[1], 0, 0)
        body += b"smpl" + struct.pack("<I", len(s)) + s
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _tmp(data, suffix=".wav"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, data)
    os.close(fd)
    return path


def _sine(n, freq, rate, amp=12000, phase=0.0):
    return [int(round(amp * math.sin(2 * math.pi * freq * k / rate + phase))) for k in range(n)]


def _import(wav_bytes, name="TEST", **kw):
    disk = blank_disk(4)
    path = _tmp(wav_bytes)
    try:
        p, start, words = si.import_sound(disk, path, name, **kw)
    finally:
        os.unlink(path)
    W = load_bytes(disk)
    assert read_file(W, p)[:len(words)] == words
    return disk, p, start, words


def _loader_view(h):
    """What SYN-5.3's loader computes from a header (197-PAL1:56-280,
    LOAD.WHOLE.FILE = 1, srate != 0): last word to load (sector, word) and
    the play region from MARK.START/MARK.END (197-PAL:833-880)."""
    stereo = h[si.SF_STEREO]
    k = h[si.SF_SAMPLE_RATE]
    assert k, "srate 0 takes the old period path"

    def words(t):
        return si.time_to_index(*t, k) << stereo
    end = words(h[si.SF_DATA_END:si.SF_DATA_END + 3])
    valid = (h[2] << 24) + (h[3] << 8) + h[4]
    end = min(end, valid - 1 - stereo)                  # clamp to valid data - 1 frame
    return {"end_word": end, "mark_start": words(h[si.SF_MARK_START:si.SF_MARK_START + 3]),
            "mark_end": words(h[si.SF_MARK_END:si.SF_MARK_END + 3]), "valid": valid}


def test_time_conversion():
    # the W0 files: CLARA3 30001 frames, CLARA4 30208 frames at 50 kHz
    assert si.index_to_time(30000, 500) == (0, 600, 0)
    assert si.index_to_time(30207, 500) == (0, 604, 140)
    assert si.time_to_index(0, 604, 140, 500) == 30207
    # 44.1 kHz: INDEX_TO_TIME's 5.079 ms reads back as frame 223 (5 x 44.1
    # = 220.5 rounds down with the truncated ratio); end_time adds 1 us
    assert si.index_to_time(224, 441) == (0, 5, 79)
    assert si.time_to_index(0, 5, 79, 441) == 223
    assert si.end_time(224, 441) == (0, 5, 80)
    for k in (1, 80, 220, 221, 320, 441, 480, 500, 960, 1000):
        for i in list(range(0, 3000)) + list(range(10 ** 6, 10 ** 6 + 3000, 7)):
            assert si.time_to_index(*si.end_time(i, k), k) == i, (k, i)


def test_float_octave():
    assert si.float_octave(3.09) == si.OCTAVE_A
    assert abs(si.octave_of(4400) - 3.09) < 1e-9
    assert abs(si.octave_of(2616) - 3.00) < 1e-3        # C below A 440


def test_mono_16bit_with_loop_and_pitch():
    n = 5000
    s = _sine(n, 261.6, 50000)
    disk, p, start, words = _import(_wav([s], 50000, smpl=(60, (1000, 3999))), "SINE")
    h = words[:SECTOR_WORDS]
    sectors = -(-n // SECTOR_WORDS)
    assert len(words) == (3 + sectors) * SECTOR_WORDS
    ent = [e for e in walk(load_bytes(disk)) if e[0] == "/SINE"][0]
    assert ent[1:] == (5, start, 3 + sectors, len(words) & 0xFFFF)
    assert h[0:2] == [4, 1]                             # compat 4, raw sampled data
    assert h[2:5] == [0, n >> 8, n & 255] and h[6:9] == [0, sectors, 0]
    assert h[si.SF_SAMPLE_RATE] == 500 and h[si.SF_PERIOD_INDEX] == 600 and h[si.SF_NYQUIST] == 25000
    assert h[si.SF_STEREO] == 0 and h[si.SF_NUMBER_OF_SYMBOLS] == 4
    assert h[si.SF_HERTZ] == 2616                       # MIDI 60
    assert h[si.SF_TOTAL_LENGTH:si.SF_TOTAL_LENGTH + 3] == [0, 4000 >> 8, 4000 & 255]
    assert h[si.SF_LOOP_LENGTH:si.SF_LOOP_LENGTH + 3] == [0, 3000 >> 8, 3000 & 255]
    assert bytes(b for w in h[53:57] for b in (w & 255, w >> 8)) == b"SINE\0\0\0\0"
    lv = _loader_view(h)
    assert lv["end_word"] == n - 1 and lv["mark_start"] == 0 and lv["mark_end"] == n - 1
    f = si.parse_sound_file(words)
    assert f["chans"] == [s] and f["rate"] == 50000 and f["loop"] == (1000, 4000)
    assert abs(f["pitch"] - 261.6) < 0.05
    sym = words[SECTOR_WORDS:SECTOR_WORDS + 32]
    assert sym[0:4] == [0, 0, 0, 6] and sym[8:12] == [0, 0, 0, 1]
    assert sym[16:19] == h[9:12] == sym[24:27] and sym[27] == 3
    assert not any(words[3 * SECTOR_WORDS + n:])      # data padded with zeros


def test_stereo_24bit_44k1():
    n = 3001
    left = [v << 8 | 0x7F for v in _sine(n, 440, 44100)]      # 24-bit, low byte rounds down
    right = [v << 8 | 0x80 for v in _sine(n, 660, 44100)]     # rounds up
    _, _, _, words = _import(_wav([left, right], 44100, bits=24))
    h = words[:SECTOR_WORDS]
    assert h[si.SF_STEREO] == 1 and h[si.SF_SAMPLE_RATE] == 441 and h[si.SF_PERIOD_INDEX] == 680
    assert (h[3] << 8) + h[4] == 2 * n
    data = words[3 * SECTOR_WORDS:3 * SECTOR_WORDS + 2 * n]
    exp_l = [v >> 8 for v in left]
    exp_r = [(v >> 8) + 1 for v in right]
    assert data[0::2] == [v & 0xFFFF for v in exp_l]          # left = even word, as CLARA4
    assert data[1::2] == [v & 0xFFFF for v in exp_r]
    lv = _loader_view(h)
    assert lv["end_word"] == 2 * (n - 1) == lv["mark_end"]


def test_8bit_and_float():
    s8 = [-128, -1, 0, 1, 127]
    _, _, _, w = _import(_wav([s8], 8000, bits=8))
    assert si.parse_sound_file(w)["chans"] == [[v << 8 for v in s8]]
    fl = [-1.5, -1.0, -0.5, 0.0, 0.25, 0.99999, 1.0]
    _, _, _, w = _import(_wav([fl], 32000, bits=32, fmt=3))
    assert si.parse_sound_file(w)["chans"] == [[-32768, -32768, -16384, 0, 8192, 32767, 32767]]


def test_resample_22050():
    n = 22050 // 4
    _, _, _, w = _import(_wav([_sine(n, 1000, 22050)], 22050))
    f = si.parse_sound_file(w)
    assert f["rate"] == 22100 and w[si.SF_SAMPLE_RATE] == 221
    out = f["chans"][0]
    assert len(out) == n * 22100 // 22050
    zc = [k for k in range(1, len(out)) if out[k - 1] < 0 <= out[k]]
    freq = (len(zc) - 1) * 22100 / (zc[-1] - zc[0])
    assert abs(freq - 1000) < 1, freq                   # pitch kept
    mid = out[100:-100]
    assert 11500 < max(mid) < 12500                     # amplitude kept


def _aiff(chans, rate, loop=None, base_note=69, detune=0):
    nch, n = len(chans), len(chans[0])
    exp, mant = 16383 + 63, rate
    while not mant >> 63 & 1:                           # normalise the 80-bit float
        mant <<= 1
        exp -= 1
    comm = struct.pack(">hIh", nch, n, 16) + struct.pack(">H", exp) + mant.to_bytes(8, "big")
    ssnd = struct.pack(">II", 0, 0) + struct.pack(">%dh" % (n * nch),
                                                  *[chans[c][k] for k in range(n) for c in range(nch)])
    body = b"AIFF" + b"COMM" + struct.pack(">I", len(comm)) + comm
    body += b"SSND" + struct.pack(">I", len(ssnd)) + ssnd
    if loop:
        mark = struct.pack(">H", 2) + struct.pack(">hIB", 1, loop[0], 3) + b"beg" \
            + struct.pack(">hIB", 2, loop[1], 3) + b"end"
        body += b"MARK" + struct.pack(">I", len(mark)) + mark + (b"\0" if len(mark) & 1 else b"")
        inst = struct.pack(">BbBBBBbb", base_note, detune, 0, 127, 0, 127, 0, 0)
        inst += struct.pack(">hhh", 1, 1, 2) + struct.pack(">hhh", 0, 0, 0) + struct.pack(">h", 0)
        body += b"INST" + struct.pack(">I", len(inst)) + inst
    return b"FORM" + struct.pack(">I", len(body)) + body


def test_aiff_with_sustain_loop():
    n = 2000
    s = _sine(n, 500, 48000)
    disk = blank_disk(2)
    path = _tmp(_aiff([s, s[::-1]], 48000, loop=(500, 1500), base_note=57), ".aif")
    try:
        _, _, words = si.import_sound(disk, path, "AIFF")
    finally:
        os.unlink(path)
    f = si.parse_sound_file(words)
    assert f["chans"] == [s, s[::-1]] and f["rate"] == 48000 and f["loop"] == (500, 1500)
    assert words[si.SF_TOTAL_LENGTH + 1:si.SF_TOTAL_LENGTH + 3] == [3000 >> 8, 3000 & 255]
    assert abs(f["pitch"] - 220.0) < 0.05


def test_export_import_identity():
    s = _sine(7000, 300, 50000)
    words = si.build_sound_file([s, s[::-1]], 50000, "ROUND", loop=(10, 6000), pitch=330.0,
                                caption="a caption")
    f = si.parse_sound_file(words)
    assert f["caption"] == "a caption" and words[si.SF_ID_FIELD_BYTES] == 9
    out = _tmp(b"")
    try:
        si.export_wav(words, out)
        disk = blank_disk(2)
        _, _, again = si.import_sound(disk, out, "ROUND", caption="a caption")
    finally:
        os.unlink(out)
    assert again == words


def test_subcatalog_and_replace():
    disk = blank_disk(2)
    # a type-6 sub-catalog SUB at sector 4, 200 sectors
    disk[0:16] = struct.pack(">8H", 0x5553, 0x0042, 0, 0, 4, 200, (200 * 256) & 0xFFFF, 6)
    small = _wav([_sine(1000, 440, 50000)], 50000)
    big = _wav([_sine(20000, 440, 50000)], 50000)
    _, p, start, w1 = _import(small)          # sanity on a fresh disk
    path = _tmp(small)
    try:
        p, start, w1 = si.import_sound(disk, path, "SND", subcat="SUB")
        assert p == "SUB/SND" and start == 8                    # after SUB's 4 catalog sectors
        try:
            si.import_sound(disk, path, "SND", subcat="SUB")
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate accepted")
        open(path, "wb").write(big)
        p, start2, w2 = si.import_sound(disk, path, "SND", subcat="SUB", replace=True)
    finally:
        os.unlink(path)
    ents = {e[0]: e[1:] for e in walk(load_bytes(disk))}
    assert start2 == 8 + len(w1) // SECTOR_WORDS                # old sectors freed, appended
    assert ents["/SUB/SND"] == (5, start2, len(w2) // SECTOR_WORDS, len(w2) & 0xFFFF)
    assert read_file(load_bytes(disk), "SUB/SND")[:len(w2)] == w2
    # replacing with a smaller file reuses the allocation
    disk2 = bytearray(disk)
    path = _tmp(small)
    try:
        _, start3, w3 = si.import_sound(disk2, path, "SND", subcat="SUB", replace=True)
    finally:
        os.unlink(path)
    assert start3 == start2
    data = read_file(load_bytes(disk2), "SUB/SND")
    assert data[:len(w3)] == w3 and not any(data[len(w3):]) and len(data) == len(w2)


def test_names():
    assert si.default_name("/x/my sample-1.wav") == "MYSAMPLE"
    for bad in ("", "lower", "TOOLONGNAME", "A/B"):
        try:
            si.check_name(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_cli_create_and_export():
    d = tempfile.mkdtemp()
    img, wav, out = (os.path.join(d, n) for n in ("W1.IMG", "in.wav", "out.wav"))
    s = _sine(3000, 440, 48000)
    open(wav, "wb").write(_wav([s], 48000))
    assert si.main([img, wav, "--create", "2", "--name", "A440"]) == 0
    assert os.path.getsize(img) == 2 << 20
    assert si.main([img, "--export", "A440", out]) == 0
    assert si.read_audio(out).chans == [s]
    for p in (img, wav, out):
        os.unlink(p)
    os.rmdir(d)


def test_w0_sound_files_round_trip():
    raw = os.environ.get("SYNCLAVIER_W0_RAW")
    if not raw:
        print("  skip test_w0_sound_files_round_trip (SYNCLAVIER_W0_RAW not set)")
        return
    W = load_bytes(open(raw, "rb").read())
    # header/symbol words that legitimately differ after export -> import:
    #   CLARA3 19-20  sf.octave: another encoding of 3.09 (034078 034187 vs
    #                 SYN-5.3's own constant 061341 043702); hertz is 4400 in
    #                 both, and only hertz reaches the voice (197-PAL:858)
    #   CLARA4 27-28  MARK.END 0.600 s before DATA.END 0.604140 s: a play
    #                 region a WAV does not carry (imported files play to
    #                 DATA.END); the symbol table differs with it ($ at 0.600)
    #                 and in order (# before ORIGIN) and a stale ".SND" in
    #                 the $ entry's name padding
    expect = {"CLARA3": ({19, 20}, set()),
              "CLARA4": ({27, 28}, {3, 4, 5, 6, 11, 12, 13, 14, 17, 18, 22, 23})}
    d = tempfile.mkdtemp()
    for name, (hdr_diff, sym_diff) in expect.items():
        orig = read_file(W, name)
        wav = os.path.join(d, name + ".wav")
        f = si.export_wav(orig, wav)
        a = si.read_audio(wav)
        assert a.rate == 50000 and len(a.chans) == (2 if name == "CLARA4" else 1)
        disk = blank_disk(4)
        _, _, words = si.import_sound(disk, wav, name)
        os.unlink(wav)
        assert len(words) == len(orig)
        assert words[3 * SECTOR_WORDS:] == list(orig[3 * SECTOR_WORDS:]), "sample data"
        assert si.parse_sound_file(words)["chans"] == f["chans"]
        got_h = {i for i in range(SECTOR_WORDS) if words[i] != orig[i]}
        got_s = {i - SECTOR_WORDS for i in range(SECTOR_WORDS, 3 * SECTOR_WORDS) if words[i] != orig[i]}
        assert got_h == hdr_diff, (name, sorted(got_h))
        assert got_s == sym_diff, (name, sorted(got_s))
        lo, ln = _loader_view(orig), _loader_view(words)
        assert lo["end_word"] == ln["end_word"] and lo["valid"] == ln["valid"]
    os.rmdir(d)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
