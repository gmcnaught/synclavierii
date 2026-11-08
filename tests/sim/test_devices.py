#!/usr/bin/env python3
"""Tests for the M1.3-M1.5 device models, stdlib only.

Each device is driven the way NED's loaders and Model B runtime drive it
(see the evidence notes in sim/devices/*.py).

Run:  python3 tests/sim/test_devices.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.asm import assemble  # noqa: E402
from sim.cpu import HALT_NO_SYN_READ, HALT_NO_SYN_WRITE  # noqa: E402
from sim.devices import ExternalMemory, MulDiv, RealTimeClock, Terminal  # noqa: E402
from sim.devices import terminal as T  # noqa: E402
from sim.system import make_system  # noqa: E402


def system(src, base=0, **kw):
    cpu = make_system(**kw)
    words, labels = assemble(src, base)
    cpu.load(words, base)
    cpu.r[0o17] = base
    cpu.labels = labels
    return cpu


def run_to(cpu, label, limit=1_000_000):
    target = cpu.labels[label]
    n = 0
    while cpu.pc != target and n < limit:
        assert cpu.step(), cpu.halted
        n += 1
    assert cpu.pc == target, "did not reach %s" % label
    return n


# ------------------------------------------------------- D4567 mul/div


def test_muldiv_registers():
    m = MulDiv()
    m.write(0o5, 1000)
    m.write(0o4, 7)
    m.write(0o6, 3000)          # 1000 * 3000 + 7
    assert (m.read(0o4) << 16 | m.read(0o5)) == 3_000_007
    m.write(0o5, 0xFFFF)
    m.write(0o4, 0xFFFF)
    m.write(0o6, 0xFFFF)        # largest case still fits in 32 bits
    assert (m.d4 << 16 | m.d5) == 0xFFFF * 0xFFFF + 0xFFFF
    m.write(0o5, 0o1234)
    m.write(0o4, 0o3)
    m.write(0o7, 0o400)         # (3:1234) / 400
    n = (3 << 16) | 0o1234
    assert m.read(0o5) == n // 0o400 and m.read(0o4) == n % 0o400
    assert m.read(0o6) is None and m.read(0o7) is None


def test_muldiv_scsiload_sequence():
    # SCSILOAD: logical sector (R5:R0) / sectors-per-cylinder (R15) gives the
    # cylinder (R1) and sector (R2); then cylinder * spc + sector rebuilds it.
    cpu = system("""
            R0 TO D5
            R5 TO D4
            R15 TO D7
            D5 TO R1
            D4 TO R2
            R1 TO D5
            R2 TO D4
            R15 TO D6
            D5 TO R0
            D4 TO R5
    DONE:   RE(DONE) TO RTRA
    """)
    cpu.r[5], cpu.r[0], cpu.r[0o15] = 0o3, 0o1234, 85
    run_to(cpu, "DONE")
    n = (3 << 16) | 0o1234
    assert cpu.r[1] == n // 85 and cpu.r[2] == n % 85
    assert (cpu.r[5] << 16 | cpu.r[0]) == n


# ------------------------------------------------- D60-D63 external memory


def test_extmem_registers_and_carry():
    x = ExternalMemory(sectors=4)
    x.write(0o60, 1)
    assert x.read(0o60) == 1 and x.read(0o61) == 0
    for i in range(300):
        x.write(0o63, i)
    assert x.read(0o60) == 2 and x.read(0o61) == 300 - 256
    x.write(0o60, 1)            # writing D60 restarts at word 0
    assert [x.read(0o63) for _ in range(300)] == list(range(300))
    x.write(0o61, 5)
    assert x.read(0o63) == 256 + 5  # D61 moves within the current sector (2)
    x.write(0o60, 0o12345)      # D60 holds any 16-bit value (SCSILOAD parks data there)
    assert x.read(0o60) == 0o12345
    assert x.read(0o63) == 0o177777  # beyond installed memory: undriven bus
    x.write(0o63, 7)            # and ignores writes
    assert x.dump(0, 1) == [0]


def test_extmem_d62_and_poll():
    x = ExternalMemory(sectors=1024)
    x.write(0o60, 3)
    x.write(0o61, 7)
    x.write(0o62, 0o4321)       # D62: no auto-increment
    assert x.read(0o61) == 7 and x.read(0o62) == 0o4321
    assert x.dump(3, 8)[7] == 0o4321
    # MONITOR's POLL (MONCAT:MON): step half cards (256 sectors) until a
    # stored zero does not read back
    cpu = system("""
            IM(1) TO D60
            D60 TO LOA0
            IM(0) TO D62
            D62 TO LOA0
            PCI TO R1
            DATA 400
    LOOP:   R1 TO D60
            IM(0) TO D62
            D62 TO LOA0
            RE(DONE) TO RTNZ
            PCI TO ADD1
            DATA 400
            RE(LOOP) TO RTRA
    DONE:   RE(DONE) TO RTRA
    """, ext_sectors=1024)
    run_to(cpu, "DONE")
    assert cpu.r[1] == 1024


def test_extmem_core_to_external_and_back():
    # The CCOPY / ECOPY loops from SCSILOAD: copy 600 (octal) words from
    # core to external memory through D63, then back to another buffer.
    cpu = system("""
            R4 TO D60           ; destination sector
            PCI TO R3
            DATA 600
    CCOPY:  MR0I TO D63
            IM(1) TO SUB3
            RE(CCOPY) TO RTNZ
            D60 TO R6           ; where it ended
            D61 TO R7
            R4 TO D60
            PCI TO R3
            DATA 600
    ECOPY:  D63 TO MR1I
            IM(1) TO SUB3
            RE(ECOPY) TO RTNZ
    DONE:   RE(DONE) TO RTRA
    """)
    src = [(i * 37) & 0xFFFF for i in range(0o600)]
    cpu.load(src, 0o10000)
    cpu.r[0], cpu.r[1], cpu.r[4] = 0o10000, 0o20000, 3
    run_to(cpu, "DONE")
    assert cpu.mem[0o20000:0o20600] == src
    assert cpu.r[6] == 4 and cpu.r[7] == 0o200   # 600 octal = 1 sector + 200
    assert cpu.extmem.dump(3, 0o600) == src


# ------------------------------------------------------------ D3 clock


def test_rtc_period_and_ack():
    c = RealTimeClock(hz=200)
    c.tick(4_999_000)
    assert c.irq_bits() == 0
    c.tick(1_000)
    assert c.irq_bits() == 0o400 and c.ticks == 1
    c.tick(20_000_000)           # missed ticks coalesce
    assert c.ticks == 5
    c.write(0o3, 0)
    assert c.irq_bits() == 0
    assert c.read(0o3) == 0


def test_rtc_interrupt_counts_in_handler():
    # 100.5 ms of simulated time at 200 Hz -> 20 interrupts.
    cpu = system("""
            PCI TO R16
            DATA ENTRY
            IM(-10) TO D1       ; R17, interrupts on
    MAIN:   RE(MAIN) TO RTRA
    RETURN: IM(-10) TO D1
    ENTRY:  IM(0) TO D3         ; acknowledge, as the runtime does
            IM(1) TO ADD1
            RE(RETURN) TO RTRA
    """)
    while cpu.time_ns < 100_500_000:
        assert cpu.step()
    assert cpu.r[1] == cpu.rtc.ticks == 20


def test_rtc_read_reports_pending_tick():
    # DEVUTIL d100_disk_check: "if read(d03) then do; ...; write(d03) = 0; end"
    cpu = system("""
    WAIT:   D3 TO LOA0
            RE(WAIT) TO RTZE
            IM(0) TO D3
            D3 TO R1
    DONE:   RE(DONE) TO RTRA
    """)
    run_to(cpu, "DONE")
    assert cpu.r[0] == 1 and cpu.r[1] == 0
    assert 5_000_000 <= cpu.time_ns < 5_010_000


# --------------------------------------------------------- D50/D51 terminal


def test_terminal_status_bits_and_device_bits():
    t = Terminal(device_bits=T.D60_EXISTS | T.D24_EXISTS)
    assert t.read(0o51) == T.D60_EXISTS | T.D24_EXISTS | T.XMIT_MT
    t.feed("A")
    assert t.read(0o51) & T.CHAR_RDY and t.irq_bits() == 0o100
    assert t.read(0o50) == ord("A")
    assert not t.read(0o51) & T.CHAR_RDY and t.irq_bits() == 0


def test_terminal_transmit_timing_and_interrupt():
    t = Terminal(baud=9600)
    t.write(0o50, ord("x"))
    assert not t.read(0o51) & T.XMIT_MT
    t.tick(t.char_ns - 1)
    assert not t.read(0o51) & T.XMIT_MT and t.irq_bits() == 0
    t.tick(1)
    assert t.read(0o51) & (T.XMIT_MT | T.XMIT_IRQ) == T.XMIT_MT | T.XMIT_IRQ
    assert t.irq_bits() == 0o100
    t.write(0o51, 0)             # TTOINT acknowledge, as the runtime does
    assert t.irq_bits() == 0 and t.read(0o51) & T.XMIT_MT
    assert t.text() == "x"


def test_terminal_baud_rate_write():
    t = Terminal(baud=9600)
    t.write(0o51, 0o100000 | (1 << 8))   # b#1200 with b#enable
    assert t.baud == 1200
    t.write(0o51, 5 << 8)                # no enable bit: unchanged
    assert t.baud == 1200


def test_terminal_input_paced_by_baud_rate():
    t = Terminal(baud=9600)
    t.feed("AB")
    assert t.read(0o50) == ord("A")
    assert not t.read(0o51) & T.CHAR_RDY   # B still on the wire
    t.tick(t.char_ns)
    assert t.read(0o51) & T.CHAR_RDY and t.read(0o50) == ord("B")


POLLED_ECHO = """
    ; polled I/O as in the Model B runtime: wait for CHAR_RDY, read D50,
    ; wait for XMIT_MT, write D50; stop at carriage return.
    GETC:   D51 TO R0
            IM(2) TO TAND0
            RE(GETC) TO RTZE
            D50 TO R1
            PCI TO AND1
            DATA 177
    PUTC:   D51 TO R0
            IM(4) TO TAND0
            RE(PUTC) TO RTZE
            R1 TO D50
            IM(15) TO TSUB1
            RE(GETC) TO RTNZ
    DONE:   RE(DONE) TO RTRA
"""


def test_polled_echo_program():
    cpu = system(POLLED_ECHO)
    cpu.terminal.feed("Ready >\r")
    run_to(cpu, "DONE")
    assert cpu.terminal.text() == "Ready >\r"
    # 8 characters at 9600 baud take at least 7 character times
    assert cpu.time_ns >= 7 * cpu.terminal.char_ns


def test_interrupt_driven_input():
    # Dispatch like *RTB-7 address 715: CHAR_RDY -> read D50 (TTIINT),
    # otherwise write 0 to D51 (TTOINT acknowledge).
    cpu = system("""
            PCI TO R16
            DATA ENTRY
            PCI TO R5           ; input buffer pointer
            DATA 4000
            IM(-10) TO D1
    MAIN:   IM(1) TO ADD3       ; background work
            RE(MAIN) TO RTRA
    RETURN: IM(-10) TO D1
    ENTRY:  D51 TO R0
            IM(2) TO AND0
            RE(TTI) TO RTNZ
            IM(0) TO D51
            RE(RETURN) TO RTRA
    TTI:    D50 TO MR5I
            RE(RETURN) TO RTRA
    """)
    cpu.terminal.feed("hello")
    while cpu.r[5] < 0o4005:
        assert cpu.step()
        assert cpu.instructions < 100_000
    assert cpu.mem[0o4000:0o4005] == list(b"hello")
    cpu.run(3)                  # RTRA, PCW write: back to the main loop
    assert cpu.pcs and cpu.ion and cpu.r[3] > 0


def test_terminal_d50_read_waits_for_a_character():
    # MONITOR's input routine reads D50 without testing CHAR_RDY
    cpu = system("""
            D50 TO R0
    DONE:   RE(DONE) TO RTRA
    """)
    for _ in range(1000):
        assert cpu.step()                # held, not halted
    assert cpu.pc == 0 and cpu.waiting == 0o50 and cpu.instructions == 0
    assert cpu.wait_ns == 1000 * cpu.ns_per_transfer
    cpu.terminal.feed("A")
    run_to(cpu, "DONE")
    assert cpu.r[0] == ord("A") and cpu.waiting is None


def test_synth_stubs():
    from sim.devices import FMInterface, OriginalKeyboard
    fm = FMInterface()
    for reg, v in ((0o160, 5), (0o161, 1), (0o162, 255)):
        assert fm.write(reg, v)
    assert fm.channels == {(5, 1): 255} and fm.read(0o162) is None
    kb = OriginalKeyboard()
    kb.write(0o131, 0o105)               # CHECK KEYBOARD TYPE
    assert kb.read(0o130) == 1           # old keyboard (ORK)
    kb.write(0o131, 3)
    assert kb.read(0o130) is None        # anything else: M2


# ------------------------------------------------------------ system


def test_system_device_map_and_missing_devices():
    cpu = make_system()
    assert cpu.terminal.read(0o51) & T.D60_EXISTS
    for dev, reason in ((0o100, HALT_NO_SYN_READ), (0o6, HALT_NO_SYN_READ)):
        c = system("D%o TO R0" % dev)
        assert not c.step() and c.halted.reason == reason and c.halted.device == dev
    c = system("IM(0) TO D104")         # no floppy controller unless asked for
    assert not c.step() and c.halted.reason == HALT_NO_SYN_WRITE
    c = make_system(ext_sectors=0)
    assert c.extmem is None and not c.terminal.read(0o51) & T.D60_EXISTS


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
    print("%d tests OK" % len(tests))
