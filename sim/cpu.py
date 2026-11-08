"""ABLE Model B CPU (behavioural, instruction level).

Follows docs/instruction-set.md. Section references below (§n) are to that
document. Choices the manual leaves open are listed in docs/simulator.md
("Behaviour choices") and marked "CHOICE" here.
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
        self.model = "B"  # "C" enables ADC/SBB; D10 and MR12D are M6
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

    def _stop(self, reason, pc, word, device=None):
        self.halted = Halt(reason, pc, word, device)
        return False

    def step(self):
        """Execute one instruction. Return False if the CPU is (now) halted."""
        if self.halted:
            return False
        r = self.r
        mem = self.mem

        # 1. Fetch (§7): READ mem[PC], PC <- PC + 1
        pcr = 0o17 if self.pcs else 0o16
        pc = r[pcr]
        w = mem[pc]
        r[pcr] = (pc + 1) & M16
        if self.trace:
            self.trace(self, pc, w)
        transfers = 1

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
                val = mem[r[sv]]
            elif sk == S_MEMI:
                a = r[sv]
                val = mem[a]
                r[sv] = (a + 1) & M16
            else:  # S_IO
                if sv == PSW_DEVICE:
                    val = self.read_psw()
                else:
                    val = self.bus.read(sv)
                    if val is NO_SYN:
                        return self._stop(HALT_NO_SYN_READ, pc, w, sv)
                    if val is BUS_WAIT:
                        return self._wait(pcr, pc, sv)
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
        if self.ion and self.pcs and self.bus.irq_bits():
            # Interrupt entry (§8): disable interrupts, fetch from R16
            self.ion = False
            self.pcs = False
        return True

    def _wait(self, pcr, pc, dev):
        """Hold a read the device has not answered yet: undo the fetch and
        let one transfer time pass. No interrupt can be taken mid-transfer."""
        self.r[pcr] = pc
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
