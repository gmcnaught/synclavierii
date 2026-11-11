#!/usr/bin/env python3
"""Digital sample-to-memory (M18): the native routine trap in sim/cpu.py,
sim/devices/digstm.py, tools/stm_source.py and, with SYNCLAVIER_W0 set (the
W0-53.IMG of tools/w0_image.py), SYN-5.3 recording a source on its STM
screen into poly memory bit for bit.

Run:  python3 tests/sim/test_digstm.py
"""
import contextlib
import io
import os
import struct
import sys
import tempfile
import wave

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from sim.asm import assemble  # noqa: E402
from sim.cpu import CPU  # noqa: E402
from sim.devices.digstm import DigitalStm, Source  # noqa: E402
from sim.devices.poly import PolySynth  # noqa: E402

START, SAMPLES, UNDER, STOP, IMPORT, LMAX, RMAX, TOSS, LATCH, RELEASE, GET_RATE, SET_RATE, \
    GET_CHAN = range(64, 77)


class FakeCpu:
    def __init__(self, poly=None):
        self.r = [0] * 16
        self.time_ns = 0
        self.poly = poly


def call(ds, cpu, n, *args):
    for i, a in enumerate(args):
        cpu.r[i] = a & 0xFFFF
    ds.call(cpu, n)
    return cpu.r[0]


def test_rtnv_trap():
    """`PCI TO RTNV` + n calls the handler for n = 64-76 only; R0 gets the
    result; without a handler (the instrument) every RTNV is a no-op."""
    calls = []

    class H:
        def call(self, cpu, n):
            calls.append((n, cpu.r[0], cpu.r[1], cpu.r[2]))
            cpu.r[0] = 0o1234
    words, _ = assemble("""
        IM(3) TO R0
        IM(4) TO R1
        IM(5) TO R2
        PCI TO RTNV
        DATA 77
        PCI TO RTNV
        DATA 100
        PCI TO RTNV
        DATA 114
        PCI TO RTNV
        DATA 115
        IM(7) TO RTNV
        PCI TO RTNV
        DATA 140
DONE:   RE(DONE) TO RTRA
""")
    for handler in (None, H()):
        cpu = CPU()
        cpu.model = "D"
        cpu.native = handler
        cpu.load(words)
        cpu.run(9)
        assert cpu.pc == len(words) - 1, cpu.pc
        if handler is None:
            assert calls == [] and cpu.r[0] == 3
        else:
            assert calls == [(0o100, 3, 4, 5), (0o114, 0o1234, 4, 5)], calls
            assert cpu.r[0] == 0o1234


def test_source_file():
    """tools/stm_source.py's file: header block, big-endian words, padded."""
    s = Source([1, -1, 32767, -32768, 5], 2, 441, 44100)
    assert s.frames == 2 and s.word(1, 1) == 0x8000 and s.word(2, 0) == 0
    b = s.to_bytes()
    assert len(b) == 1024 and b[:8] == b"SYNCSTM1"
    assert struct.unpack_from(">HHHII", b, 8) == (1, 2, 441, 2, 44100)
    assert b[512:520] == bytes.fromhex("0001ffff7fff8000") and not any(b[520:])
    t = Source.from_bytes(b)
    assert (t.channels, t.rate, t.rate_hz, t.frames, t.words) == (2, 441, 44100, 2, s.words)


def test_frames_arrive_at_the_rate():
    """From start, rate x 100 frames per second of simulated time (counted as
    an accumulator of ns x rate, one frame per 10^7); samples caps at 32767;
    stop holds the count; start begins again from 0."""
    ds = DigitalStm(Source([0] * 100, 1, 441))
    cpu = FakeCpu()
    assert call(ds, cpu, GET_RATE) == 441
    assert call(ds, cpu, LATCH, 0, 0, 480) == 0 and call(ds, cpu, GET_RATE) == 480
    cpu.time_ns = 1000
    call(ds, cpu, START)
    cpu.time_ns += 20833          # 20833 x 480 = 9 999 840: not yet
    assert call(ds, cpu, SAMPLES) == 0
    cpu.time_ns += 1
    assert call(ds, cpu, SAMPLES) == 1
    cpu.time_ns += 999_999 - 20834 + 1
    assert call(ds, cpu, SAMPLES) == 48
    cpu.time_ns += 10 * 10 ** 9
    assert call(ds, cpu, SAMPLES) == 32767
    call(ds, cpu, STOP)
    n = ds.arrived
    cpu.time_ns += 10 ** 9
    call(ds, cpu, SAMPLES)
    assert ds.arrived == n
    call(ds, cpu, SET_RATE, 0)                 # out of range: ignored
    call(ds, cpu, SET_RATE, 1024)
    assert call(ds, cpu, GET_RATE) == 480
    call(ds, cpu, SET_RATE, 505)
    call(ds, cpu, START)
    assert call(ds, cpu, SAMPLES) == 0
    cpu.time_ns += 10 ** 7                     # 10 ms at 50.5 kHz
    assert call(ds, cpu, SAMPLES) == 505


def test_import_writes_poly_memory():
    """do_import writes 256 frames through D157 at the address SYN-5.3 set
    (FC 16, 17 then data at FC 18), as the CPU's own writes; lmax/rmax are
    the largest magnitudes per channel; frames past the end are 0; toss
    measures without writing; an early import sets underflowed."""
    samples = []
    for i in range(300):
        samples += [(i * 37) % 2000 - 1000, -32768 if i == 7 else i]
    src = Source(samples, 2, 480)
    for stereo in (0, 1):
        poly = PolySynth(sectors=256)
        ds = DigitalStm(src)
        ds.poly = poly
        cpu = FakeCpu()
        assert call(ds, cpu, LATCH, 0, stereo, 480) == 0
        call(ds, cpu, START)
        cpu.time_ns = 10 ** 9                  # 48000 frames
        for base in (0x300, 0x900):
            poly.write(0o155, 0)
            poly.write(0o156, 16)              # PSMWRITE: address, then data
            poly.write(0o157, base >> 8)
            poly.write(0o157, base & 0xFF)
            r0 = cpu.r[0] = 0o4321
            call(ds, cpu, IMPORT)
            assert cpu.r[0] == r0 and poly.fc == 18
        n = 256 << stereo
        want = []
        for f in range(512):
            for c in range(1 + stereo):
                want.append(src.word(f, c))
        got = list(poly.mem[0x300:0x300 + n]) + list(poly.mem[0x900:0x900 + n])
        assert got == want, stereo
        assert poly.mem[0x300 + n] == 0 and poly.mem[0x2FF] == 0
        lm = max(abs(s if s < 0x8000 else s - 0x10000) for s in want[n::1 + stereo])
        assert call(ds, cpu, LMAX) == lm
        assert call(ds, cpu, RMAX) == (0 if not stereo else 299)      # frames 256-299, then 0
        assert call(ds, cpu, UNDER) == 0
        before = bytes(poly.mem)
        call(ds, cpu, TOSS)
        assert bytes(poly.mem) == before and call(ds, cpu, LMAX) == 0
        call(ds, cpu, START)
        call(ds, cpu, TOSS)                    # no frames yet
        assert call(ds, cpu, UNDER) == 1 and call(ds, cpu, LMAX) == 1000
        assert call(ds, cpu, RMAX) == (32768 if stereo else 0)


def test_mono_stereo_mixing():
    """A stereo source recorded mono gives its left channel; a mono source
    recorded stereo the same word twice."""
    for ch, stereo, want in ((2, 0, [1, 3]), (1, 1, [1, 1, 2, 2, 3, 3, 4, 4])):
        src = Source([1, 2, 3, 4], ch, 480)
        poly = PolySynth(sectors=256)
        ds = DigitalStm(src)
        ds.poly = poly
        cpu = FakeCpu()
        call(ds, cpu, LATCH, 0, stereo, 480)
        call(ds, cpu, START)
        poly.write(0o156, 16)
        poly.write(0o157, 0)
        poly.write(0o157, 0)
        call(ds, cpu, IMPORT)
        assert list(poly.mem[:len(want)]) == want and not any(poly.mem[len(want):600])


def test_no_source():
    """Without a source latch answers 1 ("not installed"), the rate is 48.0
    kHz, imports write zeros; get_chan is 0; a mount takes effect at the
    next call with the source's rate."""
    ds = DigitalStm()
    cpu = FakeCpu(PolySynth(sectors=256))
    assert call(ds, cpu, GET_RATE) == 480
    assert call(ds, cpu, LATCH, 0, 0, 441) == 1 and call(ds, cpu, GET_RATE) == 480
    assert call(ds, cpu, GET_CHAN) == 0
    call(ds, cpu, START)
    cpu.poly.mem[5] = 7
    cpu.poly.write(0o156, 16)
    cpu.poly.write(0o157, 0)
    cpu.poly.write(0o157, 0)
    call(ds, cpu, IMPORT)
    assert cpu.poly.mem[5] == 0
    ds.mount(Source([5] * 300, 1, 441))
    assert call(ds, cpu, GET_RATE) == 441 and call(ds, cpu, LATCH, 0, 0, 441) == 0


def _wav(path, ch, width, hz, frames):
    w = wave.open(path, "wb")
    w.setnchannels(ch)
    w.setsampwidth(width)
    w.setframerate(hz)
    w.writeframes(frames)
    w.close()


def test_stm_source_tool():
    """WAV to .STM: 16-bit as it is, 24-bit keeps its top 16 bits, 8-bit
    shifted up; the rate in 100 Hz units."""
    from tools.stm_source import main
    tmp = tempfile.mkdtemp()
    try:
        cases = [(2, 2, 44100, struct.pack("<4h", 1, -2, 32767, -32768), [1, -2, 32767, -32768]),
                 (1, 3, 48000, bytes([0x11, 0x34, 0x12, 0x00, 0x00, 0x80]), [0x1234, -32768]),
                 (1, 1, 22050, bytes([128, 255, 0]), [0, 127 << 8, -128 << 8])]
        for ch, width, hz, raw, want in cases:
            src, out = os.path.join(tmp, "in.wav"), os.path.join(tmp, "out.STM")
            _wav(src, ch, width, hz, raw)
            with contextlib.redirect_stdout(io.StringIO()):
                assert main([src, out]) == 0
            s = Source.from_file(out)
            assert (s.channels, s.rate, s.rate_hz) == (ch, round(hz / 100), hz)
            assert [w - 0x10000 if w & 0x8000 else w for w in s.words] == want, (s.words, want)
    finally:
        for f in os.listdir(tmp):
            os.unlink(os.path.join(tmp, f))
        os.rmdir(tmp)


def test_syn53_records_the_source():
    """SYN-5.3 (VT640, poly, velocity keyboard, the digital STM with a 0.8 s
    stereo source at 44.1 kHz): L, C, I on the terminal open the STM record
    panel in "Dig STM Mono"; a space selects stereo; Return records, Return
    stops. The new sound file in poly memory holds the source's frames bit
    for bit (left, right interleaved), and its header says stereo, 44.1 kHz."""
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        print("  skip test_syn53_records_the_source (SYNCLAVIER_W0 not set)")
        return
    from sim.boot import boot_from_w0
    x = 12345
    samples = []
    for i in range(35280):                     # 0.8 s, stereo
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        samples += [((x >> 8) & 0x7FFF) - 0x4000, (i * 97) % 40000 - 20000]
    src = Source(samples, 2, 441, 44100)
    ds = DigitalStm(src)
    poly = PolySynth(sectors=32 * 2048)
    cpu, _ = boot_from_w0(image, poly=poly, keyboard="vpk", fm_voices=8, terminal="vt640",
                          mouse=True, dig_stm=ds)
    t0 = cpu.time_ns
    plan = [(10_600, b"L"), (11_300, b"C"), (12_000, b"I"), (12_800, b" "), (15_600, b"\r"),
            (17_200, b"\r")]
    while cpu.time_ns - t0 < 21 * 10 ** 9 and not cpu.halted:
        while plan and cpu.time_ns - t0 >= plan[0][0] * 10 ** 6:
            cpu.terminal.feed(plan.pop(0)[1])
        cpu.run(20_000)
        if not plan and ds.calls.get(RELEASE, 0):
            break
    assert cpu.halted is None, cpu.halted
    assert ds.calls.get(RELEASE) and ds.imports > 100 and ds.calls.get(TOSS), ds.calls
    assert ds.stereo == 1
    mem = poly.mem
    first = struct.pack("<16H", *src.words[:16])
    a = mem.tobytes().find(first)
    assert a >= 0 and a % 512 == 0, a
    a //= 2
    h = a - 3 * 256                             # SF.HDR sector (SAMPLITS): sector 1 of the file
    valid = mem[h + 3] * 256 + mem[h + 4]
    assert mem[h + 41] == 1 and mem[h + 42] == 441, (mem[h + 41], mem[h + 42])
    n = min(valid, len(src.words))
    assert n > 60000, valid
    assert list(mem[a:a + n]) == src.words[:n]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
