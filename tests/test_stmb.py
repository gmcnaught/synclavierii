#!/usr/bin/env python3
"""tools/stmb.py: text entry -> timbre record, and bank file write/read."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import stmb  # noqa: E402

ENTRY = """TEST FM*

SynclavierVirtualInstrumentTimbreVersion000 7 12 24 3999 99 10
SynclavierTBPIChorusC 0 0 0 1.0
SynclavierTBPIChorusF 0 0 0 0.032
SynclavierPTCarrierCoeffs 0 0 3 100.0 50.0 25.0
SynclavierPTCarrierPhases 0 0 3 0.0 5.63 11.25
SynclavierPTPIOctave 0 0 0 880.0
SynclavierPTPITran 0 0 0 7.0
SynclavierPTPITune 0 0 0 -2.51
SynclavierPTPIFMRatioC 0 0 0 4.1
SynclavierPTPIFMRatioF 0 0 0 0.051
SynclavierPTPIVEnvAttack 0 0 0 0.1
SynclavierPTPIVEnvFDecay 0 0 0 0.076
SynclavierPTPIVEnvPeak 0 0 0 17.0
SynclavierPTPIVEnvSust 0 0 0 26.9
SynclavierPTPIVEnvAdj 0 0 0 1.688
SynclavierPTPIIEnvAdj 0 0 0 1.0333
SynclavierPTPIIEnvPeak 0 0 0 944.0
SynclavierPTPIVibRate 0 0 0 6.0
SynclavierPTPIVibAttack 0 0 0 1.75
SynclavierPTPIPan 0 0 0 -63.0
SynclavierPTPITremDepth 0 0 0 32.0
SynclavierPTPITremRate 0 0 0 0.6
SynclavierPTPITremInvert 0 0 0 1
SynclavierPTPITremSync 0 0 0 1
SynclavierPTPIVolume 2 0 0 -6.021
SynclavierPTPITrack 2 0 0 0
SynclavierPTPIFrameLoopMode 0 0 0 1
SynclavierPTPIFrameLoopStart 0 0 0 1
SynclavierPTPIFrameLoopEnd 0 0 0 2
SynclavierPTCarrierCoeffs 0 1 2 100.0 50.0
SynclavierPTCarrierPhases 0 1 2 90.0 0.0
SynclavierTFPIEnable 0 0 0 1
SynclavierTFPIEnable 0 1 0 1
SynclavierTFPISpliceTime 0 1 0 0.25
SynclavierTFPIVolume 0 1 0 92.6
SynclavierTFPIPitchC 0 1 0 -1.0
SynclavierTFPIPitchF 0 1 0 -25.0
SynclavierTFPIDelay 0 1 0 0.004
SynclavierTFPIEnable 0 2 0 1
SynclavierTFPIVolume 0 2 0 0.0
"""


def _entry(d):
    p = os.path.join(d, "11-Entry.txt")
    with open(p, "w") as f:
        f.write(ENTRY)
    return stmb.parse_text(p)


def test_encode_partial_fields():
    with tempfile.TemporaryDirectory() as d:
        t, notes = stmb.encode_entry(_entry(d))
    assert notes == []
    p0 = [stmb.s16(x) for x in t["partials"][0]["params"]]
    assert p0[1] == 178                      # attack, 0.5625 ms units
    assert p0[3] == 76 and p0[4] == 170 and p0[5] == 269
    assert p0[10] == 944
    assert p0[12] == 1000                    # coef 1, phase field not used
    assert p0[13] == 500 | (1 << 10)         # coef 2, phase 5.63 deg
    assert p0[14] == 250 | (2 << 10)
    assert p0[36] == 13166                   # 880 Hz +7 semitones -2.51 cents
    assert p0[37] >> 7 == 10                 # sync sine R to L
    assert p0[38] == 600 and p0[40] == 500
    assert p0[41] == ((-50 & 0x7F) << 2) | (16 << 9)
    assert p0[42] >> 10 == 6
    assert p0[43] == 4151
    assert p0[44] == 688 | (1 << 10)
    assert t["partials"][1] is None and t["partials"][3] is None
    p2 = t["partials"][2]
    assert stmb.s16(p2["params"][36]) == -4400   # no keyboard tracking
    assert p2["params"][12] == 1000              # default coefficient 1
    assert p2["params"][43] == 1000              # default ratio 1.0
    assert p2["pinfo"][0] == stmb.PINFO and p2["pinfo"][1] == 500
    assert t["misc"][6] == 1032
    assert stmb.text_name(t["tinfo"][8:16]) == "TEST FM*"


def test_timbre_frames():
    with tempfile.TemporaryDirectory() as d:
        t, _ = stmb.encode_entry(_entry(d))
    fr = t["partials"][0]["frames"]
    assert len(fr) == 2 and all(len(f) == 172 for f in fr)
    f1 = [stmb.s16(x) for x in fr[0]]
    assert f1[:3] == [-1, 0, 172]
    assert f1[8:14] == [4, 250, 0, 0, 926, 1000]     # DEL, ATK, EXP, RND, PK, VOL
    assert f1[18:20] == [-125, 0]                    # PDEL cents, no loop here
    assert fr[0][20] == 1000 | (16 << 10)            # frames keep coef-1 phase
    w = stmb.compute_wave(fr[0][20:44])
    assert fr[0][44:] == [w[2 * i] | (w[2 * i + 1] << 8) for i in range(128)]
    f2 = [stmb.s16(x) for x in fr[1]]
    assert f2[9] == 1000 and f2[12] == 0             # default 1 s splice; volume 0
    assert f2[19] == 1                               # loop end frame -> frame 1
    assert f2[20] == 1000                            # no coefficient line: 100.0
    assert t["partials"][2]["frames"] == []


def test_rte():
    em = [("ScaleFactors", 2, [0.0]),
          ("DestinationFactors", 2, [1.0] + [0.0] * 9 + [-1.0]),   # velocity
          ("DestinationFactors", 3, [0.0] * 23 + [1.0]),            # pressure
          ("DestinationFactors", 1, [0.0, 1.0]),                    # not pinned
          ("DestinationFactors", 6, [1.0]),                         # kbd envelope
          ("DestinationFactors", 7, [1.0])]
    w, notes = stmb.encode_rte(em, present=3)
    assert w[0:5] == [2, 1024, 4, 1, 0]       # partial 1; DYN.ENV; VE.PKSUS; inv VE.ATK
    assert w[5:10] == [15, 0, 2, 0, 0]        # pressure -> V.DEPTH
    assert w[20:25] == [15, 0, 0, 0, 0]       # mod wheel destination 1 not converted
    assert notes == ["RTE source 1 destination 1 (+1)"]


def test_glide_rate():
    assert [stmb.glide_rate(x) for x in (0.0204, 0.0237, 0.0319, 0.0403)] == [700, 650, 560, 498]


def test_compute_wave():
    assert stmb.SINE[0] == 1024 and stmb.SINE[64] == 2047 and stmb.SINE[192] == 0
    assert stmb.compute_wave([0] * 24) == [128] * 256
    w = stmb.compute_wave([1000] + [0] * 23)
    assert (w[0], w[64], w[128], w[192]) == (127, 255, 127, 0)
    assert min(w) == 0 and max(w) == 255
    assert stmb.compute_wave([1000 | (16 << 10)] + [0] * 23)[0] == 255   # 90 deg


def test_bank_file_round_trip():
    with tempfile.TemporaryDirectory() as d:
        _bank_round_trip(d)


def _bank_round_trip(d):
    t, _ = stmb.encode_entry(_entry(d))
    banks = [[None] * 8 for _ in range(8)]
    banks[0][0] = t
    banks[7][7] = t
    out = os.path.join(d, "x.stmb")
    stride, need = stmb.write_file(out, banks)
    words = len(stmb.timbre_words(t)) + 7 * len(stmb.timbre_words(stmb.EMPTY))
    assert stride == 250 and need == -(-words // 256)
    w, s, rb = stmb.read_banks(out)
    assert len(w) == 2000 * 256 and s == 250
    assert stmb.timbre_words(rb[0][0]) == stmb.timbre_words(t)
    assert stmb.timbre_words(rb[7][7]) == stmb.timbre_words(t)
    assert rb[0][1]["partials"] == [None] * 4
    assert rb[0][0]["name"] == "TEST FM*"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
