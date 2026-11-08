"""Tiny ABLE assembler in NED syntax, for tests and experiments.

Mnemonics come from tools/able_disasm.py (Model B), so assembling and
disassembling are exact inverses. Supported lines:

    label:  SRC TO DST        ; comment
            DATA n | DATA label
    SRC   = R5, R5I, MR5, MR5I, PCI, D50, IM(n), RE(label)
    n     = octal, as in NED's assembler (IM(-20) is -16 decimal)

RE(label) is a 6-bit relative operand: label - (address of instruction + 1).
"""
import re

from tools.able_disasm import decode_dst, decode_src

SRC_CODES = {}
DST_CODES = {}
for _c in range(256):
    _t = decode_src(_c)[0]
    SRC_CODES.setdefault(_t, _c)
    DST_CODES.setdefault(decode_dst(_c, "B")[0], _c)


class AsmError(ValueError):
    pass


def _num(tok, labels):
    if re.fullmatch(r"-?[0-7]+", tok):
        return int(tok, 8)
    if tok in labels:
        return labels[tok]
    raise AsmError("bad number or unknown label: %r" % tok)


def _imm(v):
    if not -32 <= v <= 31:
        raise AsmError("immediate out of range: %d" % v)
    return 0o200 | (v & 0o77)


def assemble(text, base=0):
    """Return (words, labels)."""
    lines = []
    for raw in text.splitlines():
        ln = raw.split(";", 1)[0].strip()
        label = None
        m = re.match(r"^([A-Za-z_.][\w.]*):\s*(.*)$", ln)
        if m:
            label, ln = m.group(1), m.group(2)
        lines.append((label, ln.upper()))
    labels, addr = {}, base
    for label, ln in lines:  # pass 1: addresses
        if label:
            labels[label.upper()] = addr
        if ln:
            addr += 1
    words, addr = [], base
    for label, ln in lines:  # pass 2
        if not ln:
            continue
        toks = ln.split()
        if toks[0] == "DATA" and len(toks) == 2:
            words.append(_num(toks[1], labels) & 0xFFFF)
        elif len(toks) == 3 and toks[1] == "TO":
            s, d = toks[0], toks[2]
            m = re.fullmatch(r"(IM|RE)\((.+)\)", s)
            if m and m.group(1) == "IM":
                sc = _imm(_num(m.group(2), labels))
            elif m:
                sc = _imm(_num(m.group(2), labels) - (addr + 1))
            elif s in SRC_CODES:
                sc = SRC_CODES[s]
            else:
                raise AsmError("unknown source %r" % s)
            if d not in DST_CODES:
                raise AsmError("unknown destination %r" % d)
            words.append((DST_CODES[d] << 8) | sc)
        else:
            raise AsmError("cannot parse %r" % ln)
        addr += 1
    return words, labels
