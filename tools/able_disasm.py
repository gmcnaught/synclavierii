#!/usr/bin/env python3
"""ABLE (New England Digital) disassembler.

Decodes 16-bit ABLE instruction words into NED assembler syntax
("SOURCE TO DESTINATION"), using the encodings documented in
docs/instruction-set.md (ABLE Series Hardware Reference Manual, plus the
NED ABLE Series Assembler v2.07 symbol table for official mnemonics and
the Model C extensions).

Usage:
  able_disasm.py FILE [--model B|C|D] [--start OCT] [--count N] [--base OCT]
  able_disasm.py --validate LISTING     # check against a NED assembler listing

Immediates are printed in octal, as NED's assembler writes them
(IM(-20) = -16 decimal). FILE is raw big-endian 16-bit words (for example the *RTx-7.sdat runtime
packages). Addresses and numbers are octal, as in all NED documentation.

Heuristics (a disassembler cannot know which words are data):
  * the word after a 'PCI' source (377, mem[R17++]) is an in-line literal
  * relative-transfer targets are shown as '; -> addr'
"""
import argparse
import re
import struct
import sys

COND = ["TRA", "TZE", "TRC", "TMI", "TNV", "TNZ", "TNC", "TPL"]
ACC_OPS = ["LOA", "AND", "ADD", "SUB", "XOR", "RTL", "OR", "LCM"]
TEST_OPS = ["TLOA", "TAND", "TADD", "TSUB"]
EXT_OPS = {0b00: "BSOR", 0b01: "SHRA", 0b10: "ADC", 0b11: "SBB"}  # 260..277


def octal(n):
    return format(n, "o")


def imm6(s):
    """6-bit two's-complement immediate from source bits 5..0."""
    v = s & 0o77
    return v - 0o100 if v & 0o40 else v


def decode_src(s):
    """Return (text, kind, value). kind in io, imm, reg, mem."""
    if s < 0o200:
        return "D" + octal(s), "io", s
    if s < 0o300:
        v = imm6(s)
        return "IM(%s)" % (("-" + octal(-v)) if v < 0 else octal(v)), "imm", v  # NED: octal
    r = s & 0o17
    inc = "I" if s & 0o20 else ""
    if s < 0o340:
        return "R%s%s" % (octal(r), inc), "reg", r
    if s == 0o377:
        return "PCI", "mem", r
    return "MR%s%s" % (octal(r), inc), "mem", r


def decode_dst(d, model="C"):
    """Return (text, kind)."""
    if d < 0o200:
        return "D" + octal(d), "io"
    if d < 0o240:
        return "%s%d" % (ACC_OPS[(d >> 2) & 7], d & 3), "alu"
    if d < 0o260:
        return "%s%d" % (TEST_OPS[(d >> 2) & 3], d & 3), "test"
    if d < 0o300:
        op = EXT_OPS[(d >> 2) & 3]
        kind = "ext" if op in ("BSOR", "SHRA") else "ext_c"  # ADC/SBB: Model C+
        return "%s%d" % (op, d & 3), kind
    if d < 0o320:
        return "R" + octal(d & 0o17), "reg"
    if d < 0o330:
        return "A" + COND[d & 7], "jabs"
    if d < 0o340:
        return "R" + COND[d & 7], "jrel"
    r = d & 0o17
    if d & 0o20:
        if r == 0o12 and model in ("C", "D"):
            return "MR12D", "mem"  # Model C+: push (pre-decrement R12)
        return "MR%sI" % octal(r), "mem"
    return "MR" + octal(r), "mem"


def disasm_word(w, model="C"):
    d, s = (w >> 8) & 0o377, w & 0o377
    st, sk, sv = decode_src(s)
    dt, dk = decode_dst(d, model)
    return st, dt, sk, sv, dk


def disassemble(words, base=0, model="C"):
    out = []
    i = 0
    while i < len(words):
        addr, w = base + i, words[i]
        st, dt, sk, sv, dk = disasm_word(w, model)
        note = []
        if dk == "jrel" and sk == "imm":
            note.append("-> %s" % octal((addr + 1 + sv) & 0xFFFF))
        if dk == "io" and dt == "D10" and model in ("C", "D"):
            note.append("Model C RPT: repeat next instruction")
        if dk == "ext_c":
            note.append("Model C+ instruction")
        if dk == "io" and dt == "D1":
            note.append("PCW")
        if sk == "io" and st == "D1":
            note.append("PSW")
        line = "%06o  %06o  %-8s TO %-8s" % (addr & 0xFFFF, w, st, dt)
        if note:
            line += " ; " + "; ".join(note)
        out.append(line)
        i += 1
        if st == "PCI" and i < len(words):  # in-line literal
            lit = words[i]
            extra = ""
            if dk == "jrel":
                extra = " ; -> %s" % octal((base + i + 1 + lit) & 0xFFFF)
            elif dk == "jabs":
                extra = " ; -> %s" % octal(lit)
            out.append("%06o  %06o    DATA %o%s" % ((base + i) & 0xFFFF, lit, lit, extra))
            i += 1
    return out


def read_words(path):
    data = open(path, "rb").read()
    if len(data) % 2:
        data += b"\0"
    return list(struct.unpack(">%dH" % (len(data) // 2), data))


LST_RE = re.compile(r"^\s+([0-7]{6})\s+([0-7]{6})\s+\d+\s+(?:\S+:\s+)?(.*)$")
BUILTIN_SRC = re.compile(r"^(PCI|R[0-7]{1,2}I?|MR[0-7]{1,2}I?|D[0-7]{1,3})$")


def validate(listing_path, model="C"):
    """Compare decoded words with a NED assembler listing ('SRC TO DST' lines)."""
    text = open(listing_path, "rb").read().decode("latin-1").replace("\r", "\n")
    checked = mism = 0
    for ln in text.splitlines():
        m = LST_RE.match(ln)
        if not m:
            continue
        w = int(m.group(2), 8)
        toks = m.group(3).split()
        if len(toks) < 3 or toks[1] != "TO":
            continue  # DATA, TEXT, etc.
        lsrc, ldst = toks[0], toks[2]
        st, dt, sk, _, _ = disasm_word(w, model)
        ok_dst = (ldst == dt) or (ldst in ("MR12I", "MR12D") and dt in ("MR12I", "MR12D"))
        if BUILTIN_SRC.match(lsrc):
            ok_src = lsrc == st
        elif re.match(r"^IM\((-?[0-7]+)\)$", lsrc):  # numeric immediate: compare value (octal)
            ok_src = lsrc == st
        elif lsrc.startswith(("IM(", "RE(")):  # symbolic operand: class only
            ok_src = sk == "imm"
        else:  # symbolic device name etc.
            ok_src = True
        checked += 1
        if not (ok_src and ok_dst):
            mism += 1
            print("MISMATCH %s %06o: listing '%s TO %s'  decoded '%s TO %s'"
                  % (m.group(1), w, lsrc, ldst, st, dt))
    print("validated %d instruction words, %d mismatches" % (checked, mism))
    return mism == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--model", default="C", choices="ABCD")
    ap.add_argument("--start", default="0", help="first word offset (octal)")
    ap.add_argument("--count", type=int, default=0, help="number of words (0 = all)")
    ap.add_argument("--base", default=None, help="address of word 0 (octal, default 0)")
    ap.add_argument("--validate", metavar="LISTING")
    a = ap.parse_args()
    if a.validate:
        sys.exit(0 if validate(a.validate, a.model) else 1)
    if not a.file:
        ap.error("FILE or --validate required")
    words = read_words(a.file)
    start = int(a.start, 8)
    end = start + a.count if a.count else len(words)
    base = int(a.base, 8) if a.base else 0
    print("\n".join(disassemble(words[start:end], base + start, a.model)))


if __name__ == "__main__":
    main()
