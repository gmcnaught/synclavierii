#!/usr/bin/env python3
"""Unit tests for the ABLE Model B CPU (sim/cpu.py), stdlib only.

One test per source and destination class, flag edge cases, conditional and
relative transfers, PSW/PCW, interrupts and halts. References (§n) are to
docs/instruction-set.md.

Run:  python3 tests/sim/test_cpu.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim import CPU, NO_SYN, Bus, Device  # noqa: E402
from sim.asm import assemble  # noqa: E402
from sim.cpu import (  # noqa: E402
    HALT_NO_SYN_READ, HALT_NO_SYN_WRITE, HALT_REQUEST, HALT_UNIMPLEMENTED)


class FakeDevice(Device):
    def __init__(self, numbers, value=0):
        self.numbers = numbers
        self.value = value
        self.writes = []
        self.irq = 0
        self.ns = 0

    def read(self, dev):
        return self.value

    def write(self, dev, value):
        self.writes.append((dev, value))
        return True

    def tick(self, ns):
        self.ns += ns

    def irq_bits(self):
        return self.irq


def make(src, regs=None, flags=None, devices=(), base=0):
    """Assemble src at base, set registers, return a CPU ready to run."""
    bus = Bus()
    for d in devices:
        bus.attach(d)
    cpu = CPU(bus)
    words, labels = assemble(src, base)
    cpu.load(words, base)
    cpu.r[0o17] = base
    for k, v in (regs or {}).items():
        cpu.r[k] = v & 0xFFFF
    if flags:
        cpu.z, cpu.c, cpu.m = flags
    cpu.labels = labels
    return cpu


def run1(src, **kw):
    cpu = make(src, **kw)
    assert cpu.step(), cpu.halted
    return cpu


def flags(cpu):
    return (cpu.z, cpu.c, cpu.m)


# ------------------------------------------------------------------ INIT


def test_init_state():
    cpu = CPU()
    assert cpu.pcs and cpu.pc_reg == 0o17 and not cpu.ion
    assert cpu.r == [0] * 16 and flags(cpu) == (False, False, False)
    assert cpu.halted is None


# ---------------------------------------------------------------- sources


def test_source_immediate_sign_extension():
    assert run1("IM(37) TO R1").r[1] == 31
    assert run1("IM(-40) TO R1").r[1] == 0xFFE0  # -32
    assert run1("IM(-1) TO R1").r[1] == 0xFFFF
    assert run1("IM(0) TO R1").r[1] == 0


def test_source_immediate_skips_read_cycle():
    assert run1("IM(5) TO R1").transfers == 2  # fetch + write
    assert run1("R2 TO R1").transfers == 3     # fetch + read + write


def test_source_register_and_post_increment():
    cpu = run1("R5 TO R1", regs={5: 0o1234})
    assert cpu.r[1] == 0o1234 and cpu.r[5] == 0o1234
    cpu = run1("R5I TO R1", regs={5: 0o1234})
    assert cpu.r[1] == 0o1234 and cpu.r[5] == 0o1235
    cpu = run1("R5I TO R1", regs={5: 0xFFFF})
    assert cpu.r[1] == 0xFFFF and cpu.r[5] == 0  # wraps


def test_source_memory_and_post_increment():
    cpu = make("MR5 TO R1", regs={5: 0o2000})
    cpu.mem[0o2000] = 0o4321
    cpu.step()
    assert cpu.r[1] == 0o4321 and cpu.r[5] == 0o2000
    cpu = make("MR5I TO R1", regs={5: 0o2000})
    cpu.mem[0o2000] = 0o4321
    cpu.step()
    assert cpu.r[1] == 0o4321 and cpu.r[5] == 0o2001


def test_source_pci_literal():
    cpu = run1("PCI TO R1\nDATA 177777", base=0o100)
    assert cpu.r[1] == 0xFFFF and cpu.pc == 0o102


def test_source_register_post_increment_then_destination_same_register():
    # Source READ (with increment) happens before destination WRITE.
    assert run1("R1I TO R1", regs={1: 7}).r[1] == 7


def test_source_io_read():
    dev = FakeDevice([0o50], value=0o101)
    cpu = run1("D50 TO R1", devices=[dev])
    assert cpu.r[1] == 0o101


def test_source_io_no_syn_halts():
    cpu = make("D50 TO R1", regs={1: 9})
    assert not cpu.step()
    assert cpu.halted.reason == HALT_NO_SYN_READ and cpu.halted.device == 0o50
    assert cpu.halted.pc == 0 and cpu.r[1] == 9
    assert not cpu.step()  # stays halted


# ----------------------------------------------------------- destinations


def test_destination_load_register_keeps_flags():
    cpu = run1("IM(0) TO R7", regs={7: 5}, flags=(False, True, True))
    assert cpu.r[7] == 0 and flags(cpu) == (False, True, True)


def test_destination_load_pc_is_jump():
    cpu = run1("PCI TO R17\nDATA 4000")
    assert cpu.pc == 0o4000


def test_destination_memory_and_post_increment():
    cpu = run1("IM(7) TO MR4", regs={4: 0o3000})
    assert cpu.mem[0o3000] == 7 and cpu.r[4] == 0o3000
    cpu = run1("IM(7) TO MR4I", regs={4: 0o3000})
    assert cpu.mem[0o3000] == 7 and cpu.r[4] == 0o3001


def test_destination_mr12i_is_plain_post_increment_on_model_b():
    cpu = run1("IM(3) TO MR12I", regs={0o12: 0o3000})
    assert cpu.mem[0o3000] == 3 and cpu.r[0o12] == 0o3001


def test_destination_io_write():
    dev = FakeDevice([0o51])
    cpu = run1("IM(-1) TO D51", devices=[dev])
    assert dev.writes == [(0o51, 0xFFFF)]
    assert dev.ns == cpu.time_ns > 0


def test_destination_io_no_syn_halts():
    cpu = make("IM(1) TO D100")
    assert not cpu.step()
    assert cpu.halted.reason == HALT_NO_SYN_WRITE and cpu.halted.device == 0o100


def test_model_c_destinations_do_nothing_on_model_b():
    # ORK-LM's Model C probe must find R0 still 0 on a Model B
    cpu = make("""
        IM(0) TO R0
        IM(0) TO ADD0
        IM(5) TO ADC0
        R1 TO SBB3
    """)
    cpu.r[1], cpu.r[3] = 7, 9
    for _ in range(4):
        assert cpu.step()
    assert cpu.r[0] == 0 and cpu.r[3] == 9 and cpu.z and not cpu.c


def test_adc_sbb_32_bit_arithmetic_on_model_c():
    # 32-bit add R1:R0 + R3:R2 the way the Model C runtime does it
    cpu = make("""
        R2 TO ADD0
        R3 TO ADC1
        R2 TO SUB0
        R3 TO SBB1
    """)
    cpu.model = "C"
    cpu.r[0], cpu.r[1] = 0xFFFF, 0x0001      # 0x1FFFF
    cpu.r[2], cpu.r[3] = 0x0001, 0x0002      # 0x20001
    cpu.step(); cpu.step()
    assert (cpu.r[1], cpu.r[0]) == (0x0004, 0x0000) and not cpu.c
    cpu.step(); cpu.step()                   # subtract it again
    assert (cpu.r[1], cpu.r[0]) == (0x0001, 0xFFFF) and cpu.c   # C = no borrow
    cpu = make("IM(5) TO ADC0")              # Release L ORK-LM, Model C path
    cpu.model = "C"
    cpu.c = True
    cpu.step()
    assert cpu.r[0] == 6 and not cpu.z


def test_model_c_repeat_runs_next_instruction_n_plus_1_times():
    # runtime A.STA: "R1 to D10; im(0) to MR2I" clears (R1 mod 256) + 1 words
    dev = FakeDevice([0o120])
    cpu = make("""
        R1 TO D10
        IM(0) TO MR2I
        IM(7) TO R3
    """, regs={1: 3, 2: 0o3000}, devices=[dev])
    cpu.model = "C"
    for a in range(0o3000, 0o3006):
        cpu.mem[a] = 0o55
    cpu.ion = True
    dev.irq = 1 << 10                     # pending, but not taken inside the repeat
    assert cpu.step()                     # R1 TO D10
    assert cpu.pcs                        # (taken here would mean before the repeat)
    cpu.ion, dev.irq = True, 0
    for _ in range(4):
        cpu.step()
    assert cpu.mem[0o3000:0o3004] == [0] * 4 and cpu.mem[0o3004] == 0o55
    assert cpu.r[2] == 0o3004 and cpu.pc == 2 and cpu.r[3] == 0
    cpu.step()
    assert cpu.r[3] == 7


def test_model_c_repeat_holds_interrupts():
    dev = FakeDevice([0o120])
    cpu = make("""
        IM(2) TO D10
        IM(1) TO ADD0
        IM(0) TO R3
    """, devices=[dev])
    cpu.model = "C"
    cpu.ion = True
    cpu.step()
    dev.irq = 1 << 10
    for _ in range(2):
        cpu.step()
        assert cpu.pcs                    # no interrupt during the repeats
    cpu.step()                            # third execution: the repeat ends
    assert cpu.r[0] == 3 and not cpu.pcs  # interrupt taken right after it


def test_model_c_link_register_and_r12_stack():
    # procedure call as the Model C compiler emits it: PCI TO ATRA + address;
    # prologue D10 TO MR12D (store, then decrement R12); return
    # R12I TO ATNV (back up) and MR12 TO ATRA
    cpu = make("""
        PCI TO ATRA
        DATA PROC
        IM(5) TO R1
        HALT: RE(HALT) TO RTRA
        PROC: D10 TO MR12D
        IM(7) TO R0
        R12I TO ATNV
        MR12 TO ATRA
    """, regs={0o12: 0o4000})
    cpu.model = "C"
    cpu.step()
    assert cpu.ppc == 2 and cpu.pc == cpu.labels["PROC"]
    cpu.step()
    assert cpu.r[0o12] == 0o3777 and cpu.mem[0o4000] == 2      # store, then decrement
    cpu.run(3)
    assert cpu.r[0o12] == 0o4000 and cpu.pc == 2 and cpu.r[0] == 7
    cpu.step()
    assert cpu.r[1] == 5


def test_model_c_no_interrupt_right_after_pcw_write():
    # SREG's "R14 to D1; D10 to ATRA" must not be split by an interrupt
    dev = FakeDevice([0o120])
    dev.irq = 1 << 10
    cpu = make("""
        R14 TO D1
        IM(5) TO R1
        IM(6) TO R2
    """, regs={0o14: 0o177770}, devices=[dev])     # PCS=1, ICS=1, ION=1
    cpu.model = "C"
    cpu.step()
    assert cpu.pcs and cpu.ion                    # not taken yet
    cpu.step()
    assert cpu.r[1] == 5 and not cpu.pcs          # taken after the next one
    cpu = make("R14 TO D1\nIM(5) TO R1", regs={0o14: 0o177770}, devices=[dev])
    cpu.step()                                     # Model B: taken at once
    assert not cpu.pcs


def test_model_c_no_interrupt_between_call_and_prologue():
    dev = FakeDevice([0o120])
    cpu = make("""
        IM(4) TO ATRA
        IM(0) TO R0
        IM(0) TO R0
        IM(0) TO R0
        PROC: D10 TO R5
        IM(1) TO R1
    """, devices=[dev])
    cpu.model, cpu.ion = "C", True
    dev.irq = 1 << 10
    cpu.step()                                     # the call: no interrupt yet
    assert cpu.pcs and cpu.pc == 4
    cpu.step()                                     # D10 read with the right link
    assert cpu.r[5] == 1 and not cpu.pcs


def test_model_c_priority_encoder():
    cpu = make("""
        R0 TO D2
        D2 TO R1
        R3 TO D2
        D2 TO R2
    """, regs={0: 0o4101, 3: 0})
    cpu.model = "C"
    cpu.run(4)
    assert cpu.r[1] == 2 * 11 and cpu.r[2] == 0


def test_model_d_paging_fetches_code_and_literals_from_the_page():
    from sim.devices.extmem import ExternalMemory
    # after a D11 write the very next fetch comes from the new page (NED
    # RTP/INTRO PGSW: "IM(0) to D11 (EXT)" then "R15 to ATRA (INT)"), so the
    # code continues at the same address on the other page
    cpu = make("""
        PCI TO D11
        DATA 400
    """)
    ext = ExternalMemory(sectors=512)
    page1, _ = assemble("""
        PCI TO R0
        DATA 1234
        MR4 TO R1
        D57 TO R2
        IM(0) TO D11
    """, 2)
    for i, w in enumerate(page1):
        ext.data[65536 + 2 + i] = w
    internal, _ = assemble("IM(1) TO R5", 7)
    cpu.mem[2:7] = [0o77] * 5             # different code at 2-6 in internal memory
    cpu.mem[7] = internal[0]
    cpu.mem[0o2000] = 0o4321
    cpu.model, cpu.extmem = "D", ext
    cpu.r[4] = 0o2000
    cpu.step()
    assert cpu.page == 0o400 and cpu.pc == 2
    cpu.run(3)
    assert cpu.r[0] == 0o1234 and cpu.r[1] == 0o4321 and cpu.r[2] == 1
    cpu.step()                             # IM(0) TO D11
    assert cpu.page == 0 and cpu.pc == 7
    cpu.step()
    assert cpu.r[5] == 1


def test_model_d_page_register_holds_the_page_byte_only():
    # RTP/INTRO A.PGX with a negative delta: IM(0) TO BSOR3 (-5 -> 175777),
    # D11 TO ADD3, R3 TO D11: page 25 - 5 = 20 only if D11 reads low byte 0
    cpu = make("""
        PCI TO D11
        DATA 12517
    """)
    cpu.model = "D"
    cpu.step()
    assert cpu.page == 0o12400
    cpu = make("D11 TO ADD3\nR3 TO D11", regs={3: 0o175777})
    cpu.model, cpu.page = "D", 0o12400
    cpu.pcs, cpu.r[0o16] = False, 0            # run it from internal memory (R16)
    cpu.step()
    assert (cpu.r[3] >> 8) == 0o20


def test_model_d_interrupt_level_fetches_from_internal_memory():
    from sim.devices.extmem import ExternalMemory
    dev = FakeDevice([0o120])
    cpu = make("ENTRY: IM(3) TO R6", base=0o200)
    ext = ExternalMemory(sectors=512)
    page1, _ = assemble("LOOP: IM(1) TO ADD0\nRE(LOOP) TO RTRA", 0o10)
    for i, w in enumerate(page1):
        ext.data[65536 + 0o10 + i] = w
    cpu.model, cpu.extmem, cpu.page = "D", ext, 0o400
    cpu.bus.attach(dev)
    cpu.r[0o17], cpu.r[0o16] = 0o10, 0o200
    cpu.ion = True
    cpu.run(3)
    assert cpu.r[0] == 2
    dev.irq = 1 << 10
    cpu.step()
    assert not cpu.pcs and cpu.ppc == cpu.r[0o17]
    cpu.step()                             # R16 = 200: internal memory, page unchanged
    assert cpu.r[6] == 3 and cpu.page == 0o400


# --------------------------------------------------- arithmetic and logic


def alu(op, acc, src, start=(False, False, False)):
    cpu = run1("R4 TO %s1" % op, regs={1: acc, 4: src}, flags=start)
    return cpu.r[1], flags(cpu)


def test_load():
    assert alu("LOA", 9, 0) == (0, (True, False, False))
    assert alu("LOA", 0, 0x8000) == (0x8000, (False, False, True))
    # CHOICE: C "undefined" -> unchanged
    assert alu("LOA", 0, 1, start=(False, True, False)) == (1, (False, True, False))


def test_and_or_xor_lcm():
    assert alu("AND", 0o170017, 0o7777)[0] == 0o17
    assert alu("AND", 0o170000, 0o7777) == (0, (True, False, False))
    assert alu("OR", 0o100000, 1) == (0o100001, (False, False, True))
    assert alu("XOR", 0o5555, 0o5555) == (0, (True, False, False))
    assert alu("XOR", 0o5555, 0o177777)[0] == 0o172222
    assert alu("LCM", 123, 0) == (0xFFFF, (False, False, True))
    assert alu("LCM", 0, 0xFFFF) == (0, (True, False, False))


def test_add_carry():
    assert alu("ADD", 2, 3) == (5, (False, False, False))
    assert alu("ADD", 0xFFFF, 1) == (0, (True, True, False))
    assert alu("ADD", 0x8000, 0x8001) == (1, (False, True, False))
    assert alu("ADD", 0x7FFF, 1) == (0x8000, (False, False, True))
    # Rn ADD Rn shifts left (§3)
    cpu = run1("R1 TO ADD1", regs={1: 0o140001})
    assert cpu.r[1] == 0o100002 and cpu.c


def test_subtract_not_borrow():
    assert alu("SUB", 5, 3) == (2, (False, True, False))
    assert alu("SUB", 5, 5) == (0, (True, True, False))
    assert alu("SUB", 3, 5) == (0xFFFE, (False, False, True))
    assert alu("SUB", 0, 0xFFFF) == (1, (False, False, False))


def test_rotate_left():
    # src ignored, Z unchanged, C = old bit 15, M from result (§3)
    assert alu("RTL", 0x8001, 0, start=(True, False, False)) == (3, (True, True, False))
    assert alu("RTL", 0x4000, 0, start=(False, True, False)) == (0x8000, (False, False, True))
    assert alu("RTL", 0, 0o77, start=(False, False, True)) == (0, (False, False, False))


def test_test_destinations_leave_accumulator():
    for op, acc, src, fl in (("TLOA", 1, 0, (True, False, False)),
                             ("TAND", 0o17, 0o20, (True, False, False)),
                             ("TADD", 0xFFFF, 1, (True, True, False)),
                             ("TSUB", 3, 5, (False, False, True))):
        cpu = run1("R4 TO %s2" % op, regs={2: acc, 4: src})
        assert cpu.r[2] == acc and flags(cpu) == fl, op


def test_byte_swap_with_or():
    cpu = run1("IM(0) TO BSOR3", regs={3: 0o177400})
    assert cpu.r[3] == 0o377 and flags(cpu) == (False, False, False)
    cpu = run1("IM(1) TO BSOR3", regs={3: 0o000377})
    assert cpu.r[3] == 0o177401 and cpu.m


def test_shift_right_with_add():
    cpu = run1("IM(0) TO SHRA0", regs={0: 0o100001})
    assert cpu.r[0] == 0o40000 and flags(cpu) == (False, True, False)
    cpu = run1("IM(0) TO SHRA0", regs={0: 1})
    assert cpu.r[0] == 0 and flags(cpu) == (True, True, False)
    # right rotate idiom: shift, then add 100000 back if C (§5)
    cpu = run1("PCI TO SHRA0\nDATA 100000", regs={0: 2})
    assert cpu.r[0] == 0o100001 and not cpu.c and cpu.m


# ---------------------------------------------------------- transfers


CONDS = {  # name: (flags that make it true, flags that make it false)
    "TRA": ((False, False, False), None),
    "TZE": ((True, False, False), (False, True, True)),
    "TRC": ((False, True, False), (True, False, True)),
    "TMI": ((False, False, True), (True, True, False)),
    "TNV": (None, (True, True, True)),
    "TNZ": ((False, True, True), (True, False, False)),
    "TNC": ((True, False, True), (False, True, False)),
    "TPL": ((True, True, False), (False, False, True)),
}


def test_absolute_transfers():
    for name, (yes, no) in CONDS.items():
        if yes:
            cpu = run1("PCI TO A%s\nDATA 5000" % name, flags=yes, base=0o100)
            assert cpu.pc == 0o5000, name
            assert flags(cpu) == yes
        if no:
            cpu = run1("PCI TO A%s\nDATA 5000" % name, flags=no, base=0o100)
            assert cpu.pc == 0o102, name           # skips the literal
            assert cpu.transfers == 2, name        # destination WRITE skipped


def test_relative_transfers():
    for name, (yes, no) in CONDS.items():
        if yes:
            cpu = run1("IM(10) TO R%s" % name, flags=yes, base=0o100)
            assert cpu.pc == 0o101 + 0o10, name   # relative to the next word
        if no:
            cpu = run1("IM(10) TO R%s" % name, flags=no, base=0o100)
            assert cpu.pc == 0o101 and cpu.transfers == 1, name


def test_relative_transfer_with_literal_counts_from_after_literal():
    cpu = run1("PCI TO RTRA\nDATA 177776", base=0o100)  # -2
    assert cpu.pc == 0o102 - 2


def test_relative_label_loop():
    # sum 1..10 counting R1 down; RE() targets resolved by the assembler
    cpu = make("""
            IM(12) TO R1        ; 10
            IM(0) TO LOA0
    LOOP:   R1 TO ADD0
            IM(1) TO SUB1
            RE(LOOP) TO RTNZ
    DONE:   RE(DONE) TO RTRA
    """)
    cpu.run(200)
    assert cpu.r[0] == 55 and cpu.r[1] == 0 and cpu.pc == cpu.labels["DONE"]


def test_shift_and_add_multiply_program():
    prog = """
            IM(0) TO LOA0       ; R0 = product
    LOOP:   R2 TO TLOA2         ; multiplier zero?
            RE(DONE) TO RTZE
            IM(0) TO SHRA2      ; low bit -> C
            RE(SKIP) TO RTNC
            R1 TO ADD0
    SKIP:   R1 TO ADD1          ; multiplicand <<= 1
            RE(LOOP) TO RTRA
    DONE:   RE(DONE) TO RTRA
    """
    for a, b in ((0, 0), (3, 7), (123, 456), (0o177, 0o401), (0xFFFF, 3)):
        cpu = make(prog, regs={1: a, 2: b})
        cpu.run(2000)
        assert cpu.r[0] == (a * b) & 0xFFFF, (a, b)


def test_subroutine_call_via_absolute_transfer():
    # Model B convention: save return address in a register, then jump.
    cpu = make("""
            PCI TO R15
            DATA RET
            PCI TO ATRA
            DATA SUB
    RET:    RE(RET) TO RTRA
    SUB:    IM(25) TO R3
            R15 TO ATRA
    """)
    cpu.run(10)
    assert cpu.r[3] == 0o25 and cpu.pc == cpu.labels["RET"]


# --------------------------------------------------------- PSW / PCW


def test_psw_read_flags_and_ion():
    cpu = run1("D1 TO R5", flags=(True, False, True))
    assert cpu.r[5] == 0b101
    cpu = make("D1 TO R5", flags=(False, True, False))
    cpu.ion = True
    cpu.step()
    assert cpu.r[5] == 0b1010


def test_psw_reads_device_interrupt_bits():
    dev = FakeDevice([0o50])
    dev.irq = 1 << 6  # D50 terminal
    cpu = run1("D1 TO R5", devices=[dev])
    assert cpu.r[5] == 0o100


def test_pcw_sets_flags():
    cpu = run1("IM(-31) TO D1")  # low bits 047: PCS | M C Z
    assert flags(cpu) == (True, True, True) and cpu.pcs


def test_pcw_ion_needs_ics():
    cpu = run1("IM(-30) TO D1")  # low bits 050: PCS, ION, ICS=0
    assert not cpu.ion
    cpu = run1("IM(-10) TO D1")  # low bits 070: PCS, ICS, ION
    assert cpu.ion
    cpu = make("IM(-40) TO D1")  # low bits 040: PCS only, ION unchanged
    cpu.ion = True
    cpu.step()
    assert cpu.ion
    cpu = make("IM(-20) TO D1")  # low bits 060: PCS, ICS, ION=0 (NED idiom)
    cpu.ion = True
    cpu.step()
    assert not cpu.ion


def test_pcw_selecting_r16_disables_interrupts_and_switches_pc():
    cpu = make("IM(30) TO D1", regs={0o16: 0o7000})  # ICS, ION, PCS=0
    cpu.step()
    assert not cpu.pcs and not cpu.ion and cpu.pc == 0o7000 and cpu.r[0o17] == 1
    cpu.mem[0o7000] = assemble("D1 TO R5")[0][0]
    cpu.ion = True  # even if forced on, PSW shows ION = 0 under R16
    cpu.step()
    assert cpu.r[5] & 0o10 == 0 and cpu.r[0o16] == 0o7001


# ---------------------------------------------------------- interrupts


INTERRUPT_PROGRAM = """
            PCI TO R16          ; handler entry
            DATA ENTRY
            IM(-10) TO D1       ; 177770: PCS=1, ICS=1, ION=1
    MAIN:   IM(1) TO ADD0       ; main loop counts in R0
            RE(MAIN) TO RTRA
    RETURN: IM(-10) TO D1       ; back to R17, interrupts on
    ENTRY:  IM(1) TO ADD1       ; handler counts in R1
            IM(0) TO D120       ; acknowledge the device
            RE(RETURN) TO RTRA
"""


class AckDevice(FakeDevice):
    def write(self, dev, value):
        self.irq = 0
        return super().write(dev, value)


def test_interrupt_entry_and_return():
    dev = AckDevice([0o120])
    cpu = make(INTERRUPT_PROGRAM, devices=[dev])
    cpu.run(10)
    assert cpu.r[1] == 0 and cpu.r[0] > 0 and cpu.pcs
    before = cpu.r[0]
    dev.irq = 1 << 10
    cpu.step()  # IRQ sampled at the end of this instruction
    assert not cpu.pcs and not cpu.ion and cpu.pc == cpu.labels["ENTRY"]
    cpu.run(4)  # ADD1, D120, RTRA, PCW
    assert cpu.pcs and cpu.ion and cpu.r[1] == 1 and dev.irq == 0
    assert cpu.r[0o16] == cpu.labels["ENTRY"]  # re-armed for next time
    cpu.run(10)
    assert cpu.r[0] > before and cpu.r[1] == 1


def test_interrupt_ignored_while_disabled():
    dev = FakeDevice([0o120])
    dev.irq = 1 << 10
    cpu = make("MAIN: IM(1) TO ADD0\nRE(MAIN) TO RTRA", devices=[dev])
    cpu.run(20)
    assert cpu.pcs and cpu.r[0] == 10


def test_pending_interrupt_retaken_right_after_return():
    dev = FakeDevice([0o120])  # never acknowledges
    cpu = make(INTERRUPT_PROGRAM, devices=[dev])
    cpu.run(3)
    dev.irq = 1 << 10
    cpu.run(1 + 4)
    assert not cpu.pcs and cpu.pc == cpu.labels["ENTRY"] and cpu.r[1] == 1


# ------------------------------------------------------- halts, timing


def test_halt_request_stops_after_instruction():
    cpu = make("IM(1) TO R1\nIM(2) TO R2")
    cpu.request_halt()
    assert not cpu.step()
    assert cpu.halted.reason == HALT_REQUEST and cpu.r[1] == 1 and cpu.pc == 1


def test_run_counts_and_time():
    cpu = make("MAIN: R1 TO ADD0\nRE(MAIN) TO RTRA")
    assert cpu.run(100) == 100
    assert cpu.instructions == 100
    assert cpu.transfers == 50 * 3 + 50 * 2
    assert cpu.time_ns == cpu.transfers * cpu.ns_per_transfer


def test_no_device_on_001_is_attachable():
    try:
        Bus().attach(FakeDevice([1]))
    except ValueError:
        return
    raise AssertionError("device 001 must belong to the CPU")


def test_no_syn_constant():
    assert NO_SYN is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
