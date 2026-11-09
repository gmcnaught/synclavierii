"""ABLE CPU, Models B, C and D (behavioural, instruction level).

Follows docs/instruction-set.md. Section references below (§n) are to that
document. Choices the manual leaves open are listed in docs/simulator.md
("Behaviour choices") and marked "CHOICE" here.

Model C (instruction-set.md §9, model-c-runtime-analysis.md): ADC/SBB;
device 010 (D10): a write sets the repeat count (the next instruction runs
(n mod 256) + 1 times, uninterrupted, without new fetches), a read returns
the link `ppc` (the PC after the last taken absolute transfer, or the
interrupted PC); destination 372 (MR12D) stores at R12, then decrements
R12 (pops are R12I TO ATNV then MR12I/MR12: NED SREG/LREG, MONITOR 5.3
epilogues).

Model D (docs/release-5.3.md; NED RTP/INTRO page switch code): device 011
(D11) is the instruction page pointer, page = D11 bits 15-8; only those
bits exist (a read gives the low byte 0). The page-switch stub A.PGX adds
a byte-swapped negative delta (low byte 377) to D11 and relies on no
carry out of the low byte. While R17 is
the PC, instruction fetches and memory reads through R17 (PCI literals)
come from that page: page 0 = internal memory, page n = external memory
words n * 65536 ... (the 64K-word block of external sectors n*256 ...);
everything else (data, and fetches while R16 is the PC, i.e. at interrupt
level) uses internal memory. Device 057 (D57) reads the options bits
(bit 0: Model D).

Models C and D: device 002 (D2) is the interrupt priority encoder (NED
RTP/INTRO: "D1 TO D2  READ STATUS WORD, WRITE TO PRIORITY ENCODER" then
"D2 TO RTRA  BRANCH ON WHICH BIT IS SET" into a table of two-word jumps,
bit 0 first): a read returns 2 x the number of the highest bit set in the
last word written (0 if none), as the Model B software scan finds it.

Models C and D: no interrupt is taken at the end of an instruction that
writes the PCW (D1), only after the next one. [INF] NED RTP/INTRO SREG:
"R14 to D1 restore interrupts ... D10 to ATRA and return to our caller
(this two instruction enable/transfer sequence will NOT be interrupted)";
the Model D interrupt exit (C.PGSW: R14 to D1, MR12I to ATRA) relies on it.
"""
from collections import namedtuple

from .bus import BUS_WAIT, NO_SYN, Bus
from .decode import (
    C_ALWAYS, C_C, C_M, C_NC, C_NEVER, C_NM, C_NZ, C_Z,
    D_ADC, D_ALU, D_BSOR, D_IO, D_JABS, D_JREL, D_MEM, D_MEMI, D_REG,
    D_SHRA, D_TEST, DST_TABLE,
    OP_ADD, OP_AND, OP_LCM, OP_LOA, OP_OR, OP_RTL, OP_SUB, OP_XOR,
    S_IMM, S_IO, S_MEM, S_MEMI, S_REG, S_REGI, SRC_TABLE,
)

M16 = 0xFFFF
PSW_DEVICE = 0o001

#: Why the CPU stopped. pc is the address of the instruction involved.
Halt = namedtuple("Halt", "reason pc word device")

HALT_NO_SYN_READ = "no SYN on read"
HALT_NO_SYN_WRITE = "no SYN on write"
HALT_REQUEST = "HALT"
HALT_UNIMPLEMENTED = "unimplemented instruction"


class CPU:
    """One ABLE processor with 64K words of internal memory.

    Attributes:
      r        list of 16 registers R0-R17 (octal numbering)
      z, c, m  flags
      ion      interrupt control flip-flop
      pcs      True: R17 is the PC; False: R16 is the PC (interrupt level)
      mem      64K-word internal memory
      bus      I/O bus (devices 000-177 except 001)
      halted   None while running, else a Halt
    """

    def __init__(self, bus=None, ns_per_transfer=333):
        self.model = "B"  # "C": ADC/SBB, D10, MR12D; "D": also D11 paging, D57
        #: Model D: external memory (sim.devices.extmem.ExternalMemory) that
        #: pages 1.. map onto
        self.extmem = None
        #: Model D: D57 options word (bit 0 = Model D processor)
        self.d57 = 0o1
        self.bus = bus if bus is not None else Bus()
        #: CHOICE: about 1 us per three-transfer instruction (plan §3, risk R3)
        self.ns_per_transfer = ns_per_transfer
        self.mem = [0] * 0x10000
        self.trace = None  # callable(cpu, pc, word) before each instruction
        self.reset()

    # ------------------------------------------------------------------ state

    def reset(self):
        """INIT: PC = R17, interrupts disabled (§1, §8).

        CHOICE: registers and flags are cleared; the manual does not say
        what INIT does to them. Memory is left alone.
        """
        self.r = [0] * 16
        self.z = self.c = self.m = False
        self.ion = False
        self.pcs = True
        self.halted = None
        self._halt_request = False
        self.instructions = 0
        self.transfers = 0
        self.time_ns = 0
        self.wait_ns = 0     # time spent holding reads (BUS_WAIT)
        self.waiting = None  # device whose read is being held, if any
        self.ppc = 0         # Model C link (D10 read)
        self.rpt_next = 0    # Model C: repeats armed by a D10 write
        self.rpt_left = 0    # repeats of the current instruction still to run
        self.rpt_word = 0
        self.rpt_pc = 0
        self.page = 0        # Model D: D11
        self.d2 = 0          # Model C/D: priority encoder input
        self.int_shadow = False  # Model C/D: PCW written by this instruction

    @property
    def pc_reg(self):
        return 0o17 if self.pcs else 0o16

    @property
    def pc(self):
        return self.r[self.pc_reg]

    @pc.setter
    def pc(self, value):
        self.r[self.pc_reg] = value & M16

    def load(self, words, base=0):
        for i, w in enumerate(words):
            self.mem[(base + i) & M16] = w & M16

    def request_halt(self):
        """Assert HALT; the CPU stops at the end of the current instruction."""
        self._halt_request = True

    # ------------------------------------------------------------- PSW / PCW

    def read_psw(self):
        """PSW (§8): device interrupt bits 15-4, ION, M, C, Z.

        ION reads as 0 while R16 is the PC.
        """
        return (self.bus.irq_bits()
                | ((self.ion and self.pcs) << 3)
                | (self.m << 2) | (self.c << 1) | self.z)

    def write_pcw(self, v):
        """PCW (§8): Z C M copied to the flags; ION only when ICS = 1;
        PCS selects R17 (1) or R16 (0). Selecting R16 disables interrupts."""
        self.z = bool(v & 1)
        self.c = bool(v & 2)
        self.m = bool(v & 4)
        if v & 0o20:
            self.ion = bool(v & 0o10)
        self.pcs = bool(v & 0o40)
        if not self.pcs:
            self.ion = False

    # -------------------------------------------------------------- execution

    def _set_zm(self, v):
        self.z = v == 0
        self.m = bool(v & 0x8000)

    def _alu(self, op, acc, src):
        """Return the result of arithmetic/logical op; update the flags.

        CHOICE: where the manual says C is "undefined" (LOAD, AND, XOR, OR,
        LCM, BSOR) C is left unchanged.
        """
        if op == OP_LOA:
            res = src
        elif op == OP_AND:
            res = acc & src
        elif op == OP_ADD:
            t = acc + src
            self.c = t > M16
            res = t & M16
        elif op == OP_SUB:
            self.c = acc >= src  # C = NOT borrow
            res = (acc - src) & M16
        elif op == OP_XOR:
            res = acc ^ src
        elif op == OP_RTL:  # src ignored; Z unchanged
            self.c = bool(acc & 0x8000)
            res = ((acc << 1) | (acc >> 15)) & M16
            self.m = bool(res & 0x8000)
            return res
        elif op == OP_OR:
            res = acc | src
        else:  # OP_LCM
            res = ~src & M16
        self._set_zm(res)
        return res

    def _cond(self, c):
        if c == C_ALWAYS:
            return True
        if c == C_Z:
            return self.z
        if c == C_C:
            return self.c
        if c == C_M:
            return self.m
        if c == C_NEVER:
            return False
        if c == C_NZ:
            return not self.z
        if c == C_NC:
            return not self.c
        return not self.m  # C_NM

    def _paged(self, pcs):
        """Model D: the external memory index base of the current
        instruction page, or None for internal memory."""
        if self.model != "D" or not pcs or (self.page >> 8) == 0:
            return None
        return (self.page >> 8) << 16

    def _code_read(self, base, a):
        ext = self.extmem
        i = base + a
        if ext is None or i >= len(ext.data):
            return 0xFFFF   # CHOICE: as external memory beyond the installed size
        return ext.data[i]

    def _stop(self, reason, pc, word, device=None):
        self.halted = Halt(reason, pc, word, device)
        return False

    def step(self):
        """Execute one instruction. Return False if the CPU is (now) halted."""
        if self.halted:
            return False
        r = self.r
        mem = self.mem

        # 1. Fetch (§7): READ mem[PC], PC <- PC + 1 (Model C repeat: the
        #    same instruction again, no fetch, PC unchanged)
        pcr = 0o17 if self.pcs else 0o16
        base = self._paged(self.pcs)
        undo = (r[pcr], self.rpt_left, self.rpt_next)   # for a held read
        if self.rpt_left:
            self.rpt_left -= 1
            pc, w = self.rpt_pc, self.rpt_word
            transfers = 0
        else:
            pc = r[pcr]
            w = mem[pc] if base is None else self._code_read(base, pc)
            r[pcr] = (pc + 1) & M16
            transfers = 1
            if self.rpt_next:
                self.rpt_left, self.rpt_next = self.rpt_next, 0
                self.rpt_pc, self.rpt_word = pc, w
        if self.trace:
            self.trace(self, pc, w)

        self.waiting = None
        # 2. Source READ (skipped for immediates)
        sk, sv = SRC_TABLE[w & 0o377]
        if sk == S_IMM:
            val = sv
        else:
            transfers += 1
            if sk == S_REG:
                val = r[sv]
            elif sk == S_REGI:
                val = r[sv]
                r[sv] = (val + 1) & M16
            elif sk == S_MEM:
                if base is not None and sv == pcr:
                    val = self._code_read(base, r[sv])
                else:
                    val = mem[r[sv]]
            elif sk == S_MEMI:
                a = r[sv]
                val = mem[a] if base is None or sv != pcr else self._code_read(base, a)
                r[sv] = (a + 1) & M16
            else:  # S_IO
                if sv == PSW_DEVICE:
                    val = self.read_psw()
                elif self.model != "B" and sv == 0o10:
                    val = self.ppc
                elif self.model != "B" and sv == 0o2:
                    val = 2 * (self.d2.bit_length() - 1) if self.d2 else 0
                elif self.model == "D" and sv == 0o11:
                    val = self.page
                elif self.model == "D" and sv == 0o57:
                    val = self.d57
                else:
                    val = self.bus.read(sv)
                    if val is NO_SYN:
                        return self._stop(HALT_NO_SYN_READ, pc, w, sv)
                    if val is BUS_WAIT:
                        return self._wait(pcr, undo, sv)
                    val &= M16

        # 3. Destination WRITE (skipped for a failed conditional transfer)
        dk, da, db = DST_TABLE[w >> 8]
        write = True
        if dk == D_REG:
            r[da] = val
        elif dk == D_ALU:
            r[db] = self._alu(da, r[db], val)
        elif dk == D_JABS:
            if self._cond(da):
                self.ppc = self.pc   # Model C link: the return address
                self.pc = val
            else:
                write = False
        elif dk == D_JREL:
            if self._cond(da):
                self.pc = self.pc + val  # PC is already past the instruction
            else:
                write = False
        elif dk == D_MEM:
            mem[r[da]] = val
        elif dk == D_MEMI:
            if da == 0o12 and self.model != "B":
                a = r[da]                      # Model C: MR12D stores, then decrements
                mem[a] = val
                r[da] = (a - 1) & M16
            else:
                a = r[da]
                mem[a] = val
                r[da] = (a + 1) & M16
        elif dk == D_TEST:
            self._alu(da, r[db], val)  # flags only; acc unchanged (§4)
        elif dk == D_SHRA:
            acc = r[db]
            res = ((acc >> 1) + val) & M16
            self.c = bool(acc & 1)  # C = old bit 0 (§5)
            self._set_zm(res)
            r[db] = res
        elif dk == D_BSOR:
            acc = r[db]
            res = (((acc << 8) | (acc >> 8)) & M16) | val
            self._set_zm(res)
            r[db] = res
        elif dk == D_IO:
            if da == PSW_DEVICE:
                self.write_pcw(val)
                self.int_shadow = self.model != "B"
            elif self.model != "B" and da == 0o10:
                self.rpt_next = val & 0o377
            elif self.model != "B" and da == 0o2:
                self.d2 = val
            elif self.model == "D" and da == 0o11:
                self.page = val & 0o177400
            elif self.model == "D" and da == 0o57:
                pass
            elif not self.bus.write(da, val):
                return self._stop(HALT_NO_SYN_WRITE, pc, w, da)
        elif self.model == "B":
            # D_ADC, D_SBB on Model B: no operation. [HYP] Release L ORK-LM
            # detects Model C by "IM(0) TO R0; IM(0) TO ADD0; IM(5) TO ADC0;
            # R0 TO LOA0" and enables D10 repeat loops only if R0 <> 0, so
            # on a Model B the accumulator must stay unchanged.
            pass
        elif dk == D_ADC:
            # Model C (docs/model-c-runtime-analysis.md 3.4): acc + src + C
            t = r[db] + val + self.c
            self.c = t > M16
            res = t & M16
            self._set_zm(res)
            r[db] = res
        else:  # D_SBB: acc - src - (1 - C), C = NOT borrow (as SUB)
            acc = r[db]
            sub = val + (not self.c)
            self.c = acc >= sub
            res = (acc - sub) & M16
            self._set_zm(res)
            r[db] = res
        if write:
            transfers += 1

        # 4. End of instruction (§7): time, HALT, interrupts
        self.instructions += 1
        self.transfers += transfers
        ns = transfers * self.ns_per_transfer
        self.time_ns += ns
        self.bus.tick(ns)
        if self._halt_request:
            self._halt_request = False
            return self._stop(HALT_REQUEST, self.pc, mem[self.pc])
        if self.rpt_left or self.rpt_next:
            return True                       # no interrupt inside a repeat
        if self.int_shadow:
            self.int_shadow = False           # Model C/D: not right after a PCW write
            return True
        if self.ion and self.pcs and self.bus.irq_bits():
            # Interrupt entry (§8): disable interrupts, fetch from R16
            self.ion = False
            self.pcs = False
            self.ppc = self.r[0o17]           # Model C link: the interrupted PC
        return True

    def _wait(self, pcr, undo, dev):
        """Hold a read the device has not answered yet: undo the fetch (and
        any repeat bookkeeping) and let one transfer time pass. No interrupt
        can be taken mid-transfer."""
        self.r[pcr], self.rpt_left, self.rpt_next = undo
        self.waiting = dev
        self.wait_ns += self.ns_per_transfer
        self.time_ns += self.ns_per_transfer
        self.bus.tick(self.ns_per_transfer)
        return True

    def run(self, max_instructions=None):
        """Run until halted or max_instructions executed. Return the count."""
        n = 0
        while not self.halted and (max_instructions is None or n < max_instructions):
            if not self.step():
                break
            n += 1
        return n
