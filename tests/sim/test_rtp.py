#!/usr/bin/env python3
"""Tests for sim/rtp.py (M2.1: running the Release L real-time program).

The multi-floppy file format is tested on a synthetic image. If
SYNCLAVIER_RELEASE_L points to the user-supplied Release L .simg, ORK-LM is
started and run for 9 simulated seconds as well (skipped otherwise).

Run:  python3 tests/sim/test_rtp.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.rtp import rtp_words  # noqa: E402

S = 256


def image_with(parts):
    """Words of a tiny .simg: root catalog of type-7 floppies, each holding
    one type-8 part. parts: list of (disk number, data sectors, total)."""
    nfl = len(parts)
    W = [0] * (4 * S)
    base = 4
    for k, (disk, sectors, total) in enumerate(parts):
        flen = 2 + 1 + sectors          # catalog sector, spare, header + data
        e = k * 8
        W[e:e + 8] = [ord("F") | (ord("0") + k) << 8, 0, 0, 0, base, flen, (flen * S) & 0xFFFF, 7]
        fl = [0] * (flen * S)
        fl[0:8] = [ord("R") | ord("T") << 8, ord("P") | 0, 0, 0, 2, 1 + sectors, ((1 + sectors) * S) & 0xFFFF, 8]
        hdr = [3, ord("R") | ord("T") << 8, ord("P") | ord(" ") << 8, 0x2020, 0x2020, 1, 0, total, disk]
        fl[2 * S:2 * S + len(hdr)] = hdr
        for i in range(sectors * S):
            fl[3 * S + i] = (disk << 12) | (i & 0o7777)
        W += fl
        base += flen
    return W


def test_parts_joined_in_disk_order():
    W = image_with([(2, 2, 5), (1, 3, 5)])   # catalog order differs from disk order
    data = rtp_words(W, "RTP")
    assert len(data) == 5 * S
    assert data[0] == (1 << 12) and data[3 * S] == (2 << 12)


def test_inconsistent_headers_rejected():
    for parts in ([(1, 2, 5), (2, 2, 5)],      # 4 sectors, header says 5
                  [(1, 2, 4), (3, 2, 4)]):     # disk 2 missing
        try:
            rtp_words(image_with(parts), "RTP")
        except ValueError:
            continue
        raise AssertionError("accepted %r" % (parts,))


def test_release_l_ork_lm_runs():
    image = os.environ.get("SYNCLAVIER_RELEASE_L")
    if not image:
        print("  skip test_release_l_ork_lm_runs (SYNCLAVIER_RELEASE_L not set)")
        return
    from sim.rtp import start_rtp
    cpu, dbg, lay = start_rtp(image, "ORK-LM")
    assert lay["rtp_words"] == 673 * S
    n0 = len(cpu.terminal.out)
    t0 = cpu.time_ns
    while cpu.time_ns - t0 < 9e9:
        assert dbg.run(1_000_000) is None, dbg.report()
    text = bytes(b & 0o177 for b in cpu.terminal.out[n0:]).decode("latin-1")
    assert "WELCOME TO THE SYNCLAVIER" in text
    assert dbg.io_counts[(0o130, "R")] > 0 and dbg.io_counts[(0o160, "R")] > 0
    assert not cpu.probe.counts, cpu.probe.counts       # every device it touches is modelled
    assert cpu.keyboard.unknown_reads == 0 and cpu.fm.unknown_reads == 0
    assert "9  VOICES" in text                  # one 8-voice card detected (shown + 1)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
