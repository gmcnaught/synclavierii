#!/usr/bin/env python3
"""Generate the output reverb's constants (OSD Reverb, not on the instrument)
used by sim/pcm.py Reverb and hdl/dev/pcm_reverb.sv.

An 8-line feedback delay network at 48 kHz in one MEM_WORDS-entry delay
memory (docs/poly-output.md 9): a predelay, four series all-pass diffusers,
eight delay lines of prime lengths with a Hadamard feedback matrix. Each
reverb type sets the predelay, the line lengths (Hall's, scaled), the decay
time T60 (per-line gain g = 10^(-3 L / (T60 x 48000)) / sqrt(8), the
Hadamard's 1/sqrt(8) folded in), Jot's per-line damping and tonal
correction (from alpha = T60 at 24 kHz / T60 at DC) and the wet level. The line
reads are modulated (a triangle 0 - MOD_SPAN samples, each line at its own
rate, linear interpolation) so no high mode rings on; the input goes through
a two-stage high cut (OSD Reverb tone). Writes
sim/pcm_reverb.py and hdl/dev/pcm_reverb.svh; the committed files are the
reference, so the sim and the HDL use the same integers.

  python3 tools/gen_pcm_reverb.py           # write both files
  python3 tools/gen_pcm_reverb.py --check   # exit 1 if they differ from a fresh build
"""
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RATE = 48_000
ADDR_BITS = 15                  # delay memory addresses; its size MEM_WORDS (below) is
MEM_ROUND = 2048                # the words used rounded up to this (4 M10K of 512 x 20 each)
CLEAR_WORDS = 256               # words cleared a sample after a type change
Q = 15                          # coefficients: x / 2**15
PRE_MAX = 1200                  # 25 ms
LINE_MIN = 1680                 # line 0's longest length; line i 2**(i/7) times that
#: mode density: total line delay >= 0.15 T60 x 48000 for each type (JOS, PASP 3.7.4)
MODE_DENSITY = 0.15
AP_LEN = (241, 173, 409, 307)   # diffusers (primes, 3.6 - 8.5 ms)
AP_G = (0.6, 0.6, 0.5, 0.5)        # (0.75/0.625 left high modes ringing in the tail)
LINES = 8
SIGN = (1, -1, -1, 1, -1, 1, 1, -1)    # input to line i: SIGN[i] x d / 2
MOD_BITS = 24                   # line modulation phase: a triangle from bits 23:8
MOD_SPAN = 8                    # read delay L + 0 .. 8 samples (tri[14:12], fraction tri[11:0])
MOD_HZ = tuple(1.0 * (1 + 0.13 * i) for i in range(8))   # 1.0 - 1.91 Hz
#: OSD Reverb tone codes: the high cut's -3 dB frequency (None = full band)
TONE_HZ = (8000, 5000, 3000, None)
#: wet level codes (OSD Reverb mix, 0 = the default), dB from the type's 0 dB
MIX_DB = (-12, -6, -18, 0)
#: type code: (name, predelay ms, line-length scale, T60 s at DC,
#: alpha = T60 at half the sample rate / T60 at DC (Jot's damping, below),
#: 0 dB wet gain in dB: an impulse's wet energy = its dry energy, one side)
TYPES = {
    1: ("Room", 8, 0.393, 0.8, 0.39, 5.2),
    2: ("Hall", 25, 1.0, 2.6, 0.29, 6.9),
    3: ("Plate", 4, 0.8, 2.0, 0.44, 3.5),
}


def is_prime(n):
    return n > 1 and all(n % k for k in range(2, math.isqrt(n) + 1))


def prime_near(n):
    """The prime nearest n (the lower on a tie)."""
    for k in range(n):
        for c in (n - k, n + k):
            if is_prime(c):
                return c
    raise ValueError(n)


def tone_gain2(c, w):
    """|H(w)|^2 of one tone stage s += c ((x + x_prev) / 2 - s): a one-pole
    with a zero at half the sample rate."""
    return c * c * math.cos(w / 2) ** 2 / (1 - 2 * (1 - c) * math.cos(w) + (1 - c) ** 2)


def tone_coef(fc):
    """c of the two tone stages, the cascade 3 dB down at fc (None: Full,
    2**Q, which the reverb takes as a bypass)."""
    if fc is None:
        return 2 ** Q
    w = 2 * math.pi * fc / RATE
    lo, hi = 1e-6, 1.0
    for _ in range(100):                  # each stage 1.5 dB down, by bisection
        c = (lo + hi) / 2
        lo, hi = (c, hi) if tone_gain2(c, w) < 2 ** -0.5 else (lo, c)
    return round(2 ** Q * c)


def jot(n, t60, alpha):
    """Line gain g (Hadamard's 1/sqrt(8) folded in) and one-pole damping
    pole b (lp = y + b (lp - y)) of a line n samples long, for T60 at DC
    and alpha (Jot 1991, JOS PASP 3.7.5): the pole b = ln(10)/4 log10(g')
    (1 - 1/alpha^2), g' = 10^(-3 n / (T60 x 48000)), so every line loses
    the same dB per second at each frequency and no mode outlasts its
    neighbours."""
    g1 = 10 ** (-3 * n / (t60 * RATE))
    b = math.log(10) / 4 * math.log10(g1) * (1 - 1 / alpha ** 2)
    assert 0 <= b < 0.9, (n, t60, alpha, b)
    return g1 / math.sqrt(LINES), b


def design():
    line_max = tuple(prime_near(round(LINE_MIN * 2 ** (i / (LINES - 1)))) for i in range(LINES))
    a = 0
    pd_base = a
    a += PRE_MAX + 1
    ap_base = []
    for n in AP_LEN:
        ap_base.append(a)
        a += n + 1
    line_base = []
    for n in line_max:
        line_base.append(a)
        a += n + MOD_SPAN + 1
    words = -(-a // MEM_ROUND) * MEM_ROUND
    assert words <= 1 << ADDR_BITS and words % CLEAR_WORDS == 0, words
    types = {}
    for t, (name, pre_ms, scale, t60, alpha, mix0_db) in TYPES.items():
        lens = tuple(min(m, prime_near(round(m * scale))) for m in line_max)
        assert sum(lens) >= MODE_DENSITY * t60 * RATE, (name, sum(lens))
        gc = [jot(n, t60, alpha) for n in lens]
        mix = tuple(round(2 ** Q * 10 ** ((mix0_db + db) / 20)) for db in MIX_DB)
        types[t] = dict(name=name, pre=max(1, round(pre_ms * RATE / 1000)), lens=lens,
                        gains=tuple(round(2 ** Q * g) for g, _ in gc),
                        pole=tuple(round(2 ** Q * b) for _, b in gc),
                        tc=round(2 ** Q * (1 - alpha) / (1 + alpha)), mix=mix)
    return dict(pd_base=pd_base, ap_base=tuple(ap_base), ap_g=tuple(round(2 ** Q * g) for g in AP_G),
                mod_inc=tuple(round(f * 2 ** MOD_BITS / RATE) for f in MOD_HZ),
                mod_ph0=tuple(i << (MOD_BITS - 3) for i in range(8)),
                tone=tuple(tone_coef(f) for f in TONE_HZ),
                line_max=line_max, line_base=tuple(line_base), used=a, words=words,
                clear=words // CLEAR_WORDS, types=types)


def py_text(d):
    t = d["types"]
    lines = [
        '"""Generated by tools/gen_pcm_reverb.py: do not edit.',
        "",
        "Output reverb (OSD Reverb) constants for sim/pcm.py Reverb and",
        'hdl/dev/pcm_reverb.sv; coefficients are x / 2**Q."""',
        "",
        f"MEM_WORDS = {d['words']}",
        f"CLEAR = {d['clear']}",
        f"CLEAR_WORDS = {CLEAR_WORDS}",
        f"Q = {Q}",
        f"PD_BASE = {d['pd_base']}",
        f"AP_BASE = {d['ap_base']}",
        f"AP_LEN = {AP_LEN}",
        f"AP_G = {d['ap_g']}",
        f"LINE_BASE = {d['line_base']}",
        f"LINE_MAX = {d['line_max']}",
        f"SIGN = {SIGN}",
        f"MIX_DB = {MIX_DB}",
        f"MOD_BITS = {MOD_BITS}",
        f"MOD_SPAN = {MOD_SPAN}",
        f"MOD_INC = {d['mod_inc']}",
        f"MOD_PH0 = {d['mod_ph0']}",
        f"TONE_HZ = {TONE_HZ}",
        f"TONE = {d['tone']}",
        "#: type code 1 Room, 2 Hall, 3 Plate (0 Off): predelay, line lengths,",
        "#: line gains, line damping poles, tonal correction b (Jot's",
        "#: E(z) = (1 - b z^-1) / (1 - b), the 1 / (1 - b) in MIX), wet gain per",
        "#: OSD Reverb mix code",
        "NAME = (None, " + ", ".join(repr(t[k]["name"]) for k in (1, 2, 3)) + ")",
        "PRE = (0, " + ", ".join(str(t[k]["pre"]) for k in (1, 2, 3)) + ")",
        "LENS = ((0,) * 8, " + ", ".join(str(t[k]["lens"]) for k in (1, 2, 3)) + ")",
        "GAINS = ((0,) * 8, " + ", ".join(str(t[k]["gains"]) for k in (1, 2, 3)) + ")",
        "POLE = ((0,) * 8, " + ", ".join(str(t[k]["pole"]) for k in (1, 2, 3)) + ")",
        "TC = (0, " + ", ".join(str(t[k]["tc"]) for k in (1, 2, 3)) + ")",
        "MIX = ((0,) * 4, " + ", ".join(str(t[k]["mix"]) for k in (1, 2, 3)) + ")",
        "",
    ]
    return "\n".join(lines)


def _case(name, ret_w, sel_w, pairs):
    out = [f"function automatic logic [{ret_w - 1}:0] {name}(input logic [{sel_w - 1}:0] s);",
           "    case (s)"]
    for k, v in pairs:
        out.append(f"        {sel_w}'d{k}: {name} = {ret_w}'d{v};")
    out += [f"        default: {name} = '0;", "    endcase", "endfunction"]
    return out


def sv_text(d):
    t = d["types"]
    mask = sum(1 << i for i, s in enumerate(SIGN) if s < 0)
    lines = [
        "// Generated by tools/gen_pcm_reverb.py: do not edit.",
        "// Output reverb (OSD Reverb) constants (sim/pcm_reverb.py); coefficients x / 2**15.",
        f"// Delay memory: {d['used']} of {d['words']} words used.",
        f"localparam int RV_ADDR_BITS = {ADDR_BITS};",
        f"localparam int RV_MEM_WORDS = {d['words']};",
        f"localparam int RV_CLEAR = {d['clear']};",
        f"localparam logic [{ADDR_BITS - 1}:0] RV_PD_BASE = {ADDR_BITS}'d{d['pd_base']};",
        f"localparam logic [7:0] RV_SIGN_NEG = 8'b{mask:08b};   // bit i: line i takes -d/2",
    ]
    lines += _case("rv_ap_base", ADDR_BITS, 2, enumerate(d["ap_base"]))
    lines += _case("rv_ap_len", ADDR_BITS, 2, enumerate(AP_LEN))
    lines += _case("rv_ap_g", 17, 2, enumerate(d["ap_g"]))
    lines += _case("rv_line_base", ADDR_BITS, 3, enumerate(d["line_base"]))
    lines += _case("rv_mod_inc", 24, 3, enumerate(d["mod_inc"]))
    lines += _case("rv_mod_ph0", 24, 3, enumerate(d["mod_ph0"]))
    lines += _case("rv_tone", 17, 2, enumerate(d["tone"]))
    lines += _case("rv_pre", ADDR_BITS, 2, [(k, t[k]["pre"]) for k in (1, 2, 3)])
    lines += _case("rv_len", ADDR_BITS, 5, [(k * 8 + i, t[k]["lens"][i]) for k in (1, 2, 3) for i in range(8)])
    lines += _case("rv_gain", 17, 5, [(k * 8 + i, t[k]["gains"][i]) for k in (1, 2, 3) for i in range(8)])
    lines += _case("rv_pole", 17, 5, [(k * 8 + i, t[k]["pole"][i]) for k in (1, 2, 3) for i in range(8)])
    lines += _case("rv_tc", 17, 2, [(k, t[k]["tc"]) for k in (1, 2, 3)])
    lines += _case("rv_mix", 17, 4, [(k * 4 + m, t[k]["mix"][m]) for k in (1, 2, 3) for m in range(4)])
    lines.append("")
    return "\n".join(lines)


def main(argv):
    d = design()
    outs = {ROOT / "sim" / "pcm_reverb.py": py_text(d), ROOT / "hdl" / "dev" / "pcm_reverb.svh": sv_text(d)}
    if "--check" in argv:
        bad = [str(p) for p, txt in outs.items() if not p.exists() or p.read_text() != txt]
        if bad:
            print("out of date:", ", ".join(bad))
            return 1
        return 0
    for p, txt in outs.items():
        p.write_text(txt)
    print(f"delay memory {d['used']} of {d['words']} words ({d['words'] // 512} M10K); lines {d['line_max']}")
    for k, ty in d["types"].items():
        print(f"  {ty['name']}: pre {ty['pre']} lens {ty['lens']} gains {ty['gains']} "
              f"pole {ty['pole']} tc {ty['tc']} mix {ty['mix']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
