#!/usr/bin/env python3
"""The D32/D33 multichannel distributor (sim/devices/multi.py, M19) and,
with SYNCLAVIER_W0 set, SYN-5.3's "Analyzing Multi-Channel Connections"
finding 8 and 16 outputs.

Run:  python3 tests/sim/test_multi.py
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
from sim.devices.multi import (ON, Distributor, fm_input, poly_input,  # noqa: E402
                               route_pair, wiring)
from sim.devices.poly import PolySynth  # noqa: E402
from sim.devices.synth import FMInterface  # noqa: E402
from sim.devices.terminal import D32_EXISTS  # noqa: E402
from sim.system import make_system  # noqa: E402
from sim.voice import FMSynth  # noqa: E402

MULTI_THERE, MULTI_MAX = 0o54725, 0o54726     # SYN-5.3 globals (040-GLOB), found by watching the probe


def test_wiring():
    """Every input is one voice side; the probe's low-bit rules hold: FM
    voice v at 4i + ((v + 1) & 3) (600-INIT:1086), poly channel c at
    4i + (c & 3) (600-INIT:1342)."""
    seen = set()
    for v in range(32):
        for side in (0, 1):
            m = fm_input(v, side)
            assert wiring(m) == ("fm", v, side) and m & 3 == (v + 1) & 3
            seen.add(m)
    for p in range(96):
        for side in (0, 1):
            m = poly_input(p, side)
            assert wiring(m) == ("poly", p, side) and m & 3 == (p % 32) & 3
            seen.add(m)
    assert seen == set(range(256)) and poly_input(96, 0) is None


def test_registers():
    d = Distributor(8)
    d.write(0o32, 0o20)
    assert d.read(0o33) == 1                          # "MULTI SYSTEM INCLUDED"
    d.write(0o33, ON | 7 << 8 | 5)                    # ignored: not the port
    assert d.assignments() == {}
    d.write(0o32, 0o21)
    d.write(0o33, ON | 7 << 8 | 5)
    d.write(0o33, ON | 3 << 8 | 200)
    d.write(0o33, ON | 8 << 8 | 9)                    # output 8 of 8: not there
    assert d.assignments() == {5: 7, 200: 3}
    d.write(0o33, 5)                                  # off (output field ignored)
    d.write(0o33, 7 << 8 | 200)
    assert d.assignments() == {} and d.read(0o32) == 0
    assert d.read(0o33) == 0                          # nothing sounds


def _fm_voice(fm, v, vol, lim, pan):
    for ch, fn, val in ((2 * v + 1, 0o13, vol), (2 * v + 1, 0o12, lim), (2 * v, 0o13, pan)):
        fm.write(0o160, ch)
        fm.write(0o161, fn)
        fm.write(0o162, val)


def _find(d, start, step, outputs=None):
    """600-INIT's search: inputs 4i + start to output 7, the first that reads
    signal present; then, the first time, the output count (K + 7)."""
    for i in range(64):
        m = 4 * i + start
        d.write(0o33, ON | 7 << 8 | m)
        if d.read(0o33) & 1:
            k = 8
            while True:
                d.write(0o33, ON | (k + 7) << 8 | m)
                if not d.read(0o33) & 1 or k + 8 >= 64:
                    break
                k += 8
            d.write(0o33, m)
            return m, k
        d.write(0o33, m)
    return None, None


def test_fm_probe():
    """The FM part of the probe: voice IVOICE and its complement IVOICE ^ 1
    at full volume, all left then all right; inputs 4i + ((IVOICE + 1) & 3)
    tried in turn. Each voice side is found at its own input, and the count
    stops at the card's outputs."""
    for outputs in (8, 16):
        fm = FMInterface(voices=32)
        d = Distributor(outputs, fm=fm)
        d.write(0o32, 0o21)
        for v in range(32):
            c = v ^ 1
            for pan, side in ((0, 0), (252, 1)):
                _fm_voice(fm, v, 255, 255, pan)
                _fm_voice(fm, c, 255, 255, pan)
                m, k = _find(d, (v + 1) & 3, 4)
                assert m == fm_input(v, side) and k == outputs, (v, side, m, k)
            _fm_voice(fm, v, 0, 0, 0)
            _fm_voice(fm, c, 0, 0, 0)


def test_poly_probe():
    """The poly part: channel CHAN with PSRCVOL right 0 / left 4095 (then
    the reverse) and PSELIM 4095 (600-INIT:1290-1295, 1412-1417); inputs
    4i + (CHAN & 3). Mono cards: only the right side exists."""
    for mono in (False, True):
        poly = PolySynth(bins=2, mono=mono)
        d = Distributor(16, poly=poly)
        d.write(0o32, 0o21)

        def fc(ch, f, *words):
            poly.write(0o155, ch)
            poly.write(0o156, f)
            for x in words:
                poly.write(0o157, x)
        for chan in [c + 64 * b for b in range(2) for c in range(32)]:
            p = 32 * (chan >> 6) + (chan & 63)
            for side, vols in ((0, (0, 4095, 0, 4095)), (1, (4095, 0, 4095, 0))):
                fc(chan, 40, *vols)
                fc(chan, 36, 4095)
                m, _ = _find(d, chan & 3, 4)
                want = None if mono and side == 0 else poly_input(p, side)
                assert m == want, (chan, side, m, want)
                fc(chan, 36, 0)
                fc(chan, 40, 0, 0, 0, 0)


def test_output_pair_mix():
    """route_pair: each side goes where its input is switched; the FM
    synth's sample with pair 2 holds only voices routed to outputs 3-4."""
    assert route_pair(10, 20, (2, 3), 2) == (10, 20)
    assert route_pair(10, 20, (2, 2), 2) == (30, 0)
    assert route_pair(10, 20, (0, 1), 2) == (0, 0)
    assert route_pair(10, 20, (3, None), 2) == (0, 10)
    assert route_pair(10, 20, (2, 3), 2, mono=True) == (0, 20)
    d = Distributor(16)
    s = FMSynth(2)
    s.multi = d
    for v in (0, 1):                     # two voices, full envelope and volume
        for c, fn, val in ((2 * v, 0o13, 128), (2 * v + 1, 0o10, 255), (2 * v + 1, 0o11, 255),
                           (2 * v + 1, 0o12, 255), (2 * v + 1, 0o13, 255)):
            s.write(0, c, fn, val)
    t = 10_000_000
    mix = s.sample_int(t)
    d.write(0o32, 0o21)
    for side, out in ((0, 2), (1, 3)):
        d.write(0o33, ON | out << 8 | fm_input(1, side))
    d.pair = 2
    l2, r2 = s.sample_int(t)
    d.pair = 1
    assert s.sample_int(t) == (0, 0)
    d.pair = 0
    assert s.sample_int(t) == mix
    d.write(0o33, ON | 2 << 8 | fm_input(0, 0))
    d.write(0o33, ON | 3 << 8 | fm_input(0, 1))
    d.pair = 2
    assert s.sample_int(t) == mix and (l2, r2) != (0, 0) and l2 != mix[0]


def test_system_bit():
    cpu = make_system(synth=True, multi=16)
    assert cpu.terminal.device_bits & D32_EXISTS and cpu.multi.outputs == 16
    assert cpu.multi.fm is cpu.fm
    assert not make_system().terminal.device_bits & D32_EXISTS


def test_syn53_analyzes_connections():
    image = os.environ.get("SYNCLAVIER_W0")
    if not image:
        print("  skip test_syn53_analyzes_connections (SYNCLAVIER_W0 not set)")
        return
    from sim.boot import boot_from_w0
    for outputs in (8, 16):
        cpu, _ = boot_from_w0(image, disk_mb=30, poly=PolySynth(), keyboard="vpk", fm_voices=8,
                              multi=outputs)
        end = cpu.time_ns + 7_000_000_000
        while cpu.time_ns < end and not cpu.halted:
            cpu.run(50_000)
        assert cpu.halted is None, cpu.halted
        assert "Analyzing Multi-Channel Connections..." in cpu.terminal.text()
        assert (cpu.mem[MULTI_THERE], cpu.mem[MULTI_MAX]) == (1, outputs)
        print("  %d outputs: MULTI.THERE 1, MULTI.MAX %d" % (outputs, cpu.mem[MULTI_MAX]))


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
