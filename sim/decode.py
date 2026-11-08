"""Instruction decode tables for the ABLE simulator.

The CPU dispatches on two 256-entry tables, one for the source byte and one
for the destination byte (see docs/instruction-set.md section 2). The
classes here are checked against tools/able_disasm.py by
tests/sim/test_decode.py, so the simulator and the disassembler cannot drift
apart.
"""

# Source classes
S_IO, S_IMM, S_REG, S_REGI, S_MEM, S_MEMI = range(6)

# Destination classes
(D_IO, D_ALU, D_TEST, D_BSOR, D_SHRA, D_ADC, D_SBB,
 D_REG, D_JABS, D_JREL, D_MEM, D_MEMI) = range(12)

# Arithmetic/logical operation numbers (destination bits 12-10), table 3
OP_LOA, OP_AND, OP_ADD, OP_SUB, OP_XOR, OP_RTL, OP_OR, OP_LCM = range(8)

# Condition codes (destination bits 10-8), table 5
C_ALWAYS, C_Z, C_C, C_M, C_NEVER, C_NZ, C_NC, C_NM = range(8)


def imm6(s):
    """6-bit two's-complement immediate (source bits 5-0), as 16 bits."""
    v = s & 0o77
    return (v - 0o100) & 0xFFFF if v & 0o40 else v


def decode_src(s):
    """Return (class, value) for source byte s.

    value is the device number (S_IO), the 16-bit immediate (S_IMM) or the
    register number (all others).
    """
    if s < 0o200:
        return S_IO, s
    if s < 0o300:
        return S_IMM, imm6(s)
    r = s & 0o17
    if s < 0o320:
        return S_REG, r
    if s < 0o340:
        return S_REGI, r
    if s < 0o360:
        return S_MEM, r
    return S_MEMI, r


def decode_dst(d):
    """Return (class, a, b) for destination byte d.

    D_IO: a = device.  D_ALU: a = operation, b = accumulator.
    D_TEST: a = operation (LOA/AND/ADD/SUB), b = accumulator.
    D_BSOR/D_SHRA/D_ADC/D_SBB: b = accumulator.
    D_REG/D_MEM/D_MEMI: a = register.  D_JABS/D_JREL: a = condition.
    """
    if d < 0o200:
        return D_IO, d, 0
    if d < 0o240:
        return D_ALU, (d >> 2) & 7, d & 3
    if d < 0o260:
        return D_TEST, (d >> 2) & 3, d & 3
    if d < 0o300:
        return (D_BSOR, D_SHRA, D_ADC, D_SBB)[(d >> 2) & 3], 0, d & 3
    if d < 0o320:
        return D_REG, d & 0o17, 0
    if d < 0o330:
        return D_JABS, d & 7, 0
    if d < 0o340:
        return D_JREL, d & 7, 0
    if d < 0o360:
        return D_MEM, d & 0o17, 0
    return D_MEMI, d & 0o17, 0


SRC_TABLE = [decode_src(s) for s in range(256)]
DST_TABLE = [decode_dst(d) for d in range(256)]
