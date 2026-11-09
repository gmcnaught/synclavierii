#!/usr/bin/env python3
"""sim/devices/poly.py: the D154-D157 poly synth model (docs/poly-synth.md)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.devices.poly import (ENV_TICK_NS, F0_TICK_NS, PSEMOD, PSLCVOL, PSNUMV, PSON,  # noqa: E402
                              PSRCVOL, PSRMA, PSRON, PSWL, PSWMA, PolySynth, two_word)

PSC, PSF, PSD = 0o155, 0o156, 0o157


def _fc(p, fc, *words):
    p.write(PSF, fc)
    for w in words:
        p.write(PSD, w)


def test_detection():
    p = PolySynth(32, 512)
    p.write(PSC, 1)
    assert p.read(PSC) == 1                     # bin 0 echoes
    p.write(PSC, 65)
    assert p.read(PSC) & 255 != 65              # bin 1 absent
    p.write(PSC, 0)
    p.write(PSF, PSNUMV)
    assert [p.read(PSD) for _ in range(4)] == [0x38] * 4    # 32 voices, no FC advance
    p16 = PolySynth(16, 256)
    p16.write(PSF, PSNUMV)
    assert p16.read(PSD) == 0x14
    assert p.read(PSC) & 0o400 == 0             # old D/A controller


def test_function_code_successors():
    p = PolySynth(8, 256)
    p.write(PSC, 3)
    _fc(p, PSWL, *range(11))                    # 0..10
    assert p.read(PSF) == PSON
    _fc(p, PSEMOD, *[0] * 7)                    # 33 35 38 32 34 36 37
    assert p.read(PSF) == 37
    _fc(p, PSRCVOL, 1, 2, 3, 4)                 # R cur, L cur, R dest, L dest
    v = p.voice[3]
    assert (v.rcur, v.lcur, v.rdest, v.ldest) == (1, 2, 3, 4)
    assert p.read(PSF) == 43


def test_two_word_values():
    assert two_word(0xFFFF, 0xFFFF, True) == -1          # "wave table length of 1"
    assert two_word(0, 255, False) == 255                # "base address of 255"
    assert two_word(0x1234, 0x0356, False) == 0x3123456
    assert two_word(0xFFFF, 0xFF00 | 0x9C, True) == -100


def test_memory_and_size():
    p = PolySynth(4, 256)                                # 65536 words
    p.write(PSC, 0)
    _fc(p, PSWMA, 0x00FF, 0x00FE, 11, 22, 33)            # sector 255 word 254: 3 words
    _fc(p, PSRMA, 0x00FF, 0x00FE)
    assert [p.read(PSD) for _ in range(3)] == [11, 22, 0]   # third is beyond the end
    _fc(p, PSWMA, 0x0100, 0, 0, 0xFFFF)                  # size probe at sector 256
    _fc(p, PSRMA, 0x0100, 0)
    assert (p.read(PSD), p.read(PSD)) == (0, 0)          # not 0, -1: no memory there


def _voice(p, ch, length, base, loop=0, on=1, inc=256, mod=256):
    p.write(PSC, ch)
    neg = (-length) & 0xFFFFFFF
    lneg = (-loop) & 0xFFFFFFF
    _fc(p, PSWL, neg >> 8 & 0xFFFF, (neg >> 24) << 8 | neg & 0xFF,
        base >> 8 & 0xFFFF, (base >> 24) << 8 | base & 0xFF,
        lneg >> 8 & 0xFFFF, (lneg >> 24) << 8 | lneg & 0xFF,
        0, 1, inc - 1, 256 - mod, on)


def test_voice_end_and_loop():
    p = PolySynth(4, 256)
    _voice(p, 0, 100, 1000)                              # 100 words at F0
    _voice(p, 1, 100, 2000, loop=40, on=3)
    p.tick(100 * F0_TICK_NS - 1)
    p.write(PSC, 0)
    p.write(PSF, PSRON)
    assert p.read(PSD) == 1                              # 99 steps: word 99 playing
    p.tick(1)
    assert p.read(PSD) == 0                              # step 100 reaches the end
    p.tick(1000 * F0_TICK_NS)
    p.write(PSC, 1)
    assert p.read(PSD) == 3                              # looping
    assert 60 <= p.voice[1].pos < 100


def test_rate_divider():
    p = PolySynth(4, 256)
    _voice(p, 0, 1000, 0, inc=99, mod=200)               # 50 kHz
    p.tick(200 * F0_TICK_NS)
    p.advance()
    assert p.voice[0].pos == 99                          # 200 ticks x 99/200


def test_envelope_and_volume_ramps():
    p = PolySynth(4, 256)
    p.write(PSC, 2)
    _fc(p, PSEMOD, 4095, 4095, 64, 4095, 4095, 4095, 0)  # mod, inc, delta, cnt, acu, lim, cval
    _fc(p, PSRCVOL, 0, 0, 4095, 0)
    v = p.voice[2]
    p.tick(63 * ENV_TICK_NS)
    p.advance()
    assert v.eval == 63 * 64                             # 64 per 40 us: 2.56 ms full scale
    p.tick(ENV_TICK_NS)
    p.advance()
    assert v.eval == 4095
    p.tick(1838 * ENV_TICK_NS)
    p.advance()
    assert v.rcur == 4095 and v.lcur == 0
    q = PolySynth(4, 256)
    q.write(PSC, 0)
    _fc(q, PSRCVOL, 0, 0, 4095, 0)
    q.tick(1837 * ENV_TICK_NS)
    q.advance()
    assert q.voice[0].rcur < 4095
    q.tick(ENV_TICK_NS)
    q.advance()
    assert q.voice[0].rcur == 4095                       # "1838 counts"


def test_on_demand_equals_continuous():
    """Advancing at every tick or only at the end gives the same state."""
    def run(step):
        p = PolySynth(4, 256)
        _voice(p, 0, 5000, 0, loop=300, on=3, inc=150, mod=211)
        p.write(PSC, 0)
        _fc(p, PSEMOD, 4095, 2000, 3, 4095, 4095, 3000, 0)
        _fc(p, PSRCVOL, 0, 100, 4095, 2000)
        t = 0
        while t < 30_000_000:
            p.tick(step)
            t += step
            if step < 30_000_000:
                p.advance()
        p.advance()
        v = p.voice[0]
        return (v.pos, v.acc, v.on, v.eval, v.ecnt, v.eacu, v.rcur, v.lcur)
    assert run(333) == run(30_000_000)


def test_ghost_channels():
    p = PolySynth(8, 256)
    p.write(PSC, 40)
    _fc(p, PSLCVOL, 123)
    p.write(PSF, PSLCVOL)
    assert p.read(PSD) == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
