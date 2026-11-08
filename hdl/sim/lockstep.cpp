// Lockstep check of hdl/able_cpu.sv against the Python simulator (M4.3).
//
// Reads a trace written by `python3 -m sim.lockstep record` (format in
// sim/lockstep.py): the CPU state and 64K words of memory at the start,
// then per instruction its device events and (pc, word). The HDL CPU runs
// from the same state; every device read is answered with the recorded
// value, every device write must match the recorded one, the interrupt
// request bits are driven from the recorded PSW reads and interrupt
// entries, and every completed instruction must have the recorded pc and
// word. Register snapshots in the trace are compared as well.
//
// Usage: Vable_sim_top TRACE [max_instructions]
// Exit 0 on full agreement, 1 on the first mismatch (with context).

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#include "Vable_sim_top.h"
#include "verilated.h"

namespace {

struct Trace {
    std::vector<uint8_t> b;
    size_t p = 0;
    bool eof() const { return p >= b.size(); }
    uint8_t u8() { return b[p++]; }
    uint16_t u16() { uint16_t v = b[p] | (b[p + 1] << 8); p += 2; return v; }
    uint8_t peek() const { return eof() ? 'E' : b[p]; }
};

Vable_sim_top* top;
uint64_t cycles = 0;
std::deque<std::string> history;

void tick() {
    top->clk = 0; top->eval();
    top->clk = 1; top->eval();
    cycles++;
}

uint16_t reg(int i) { return (top->regs_flat[i / 2] >> ((i & 1) * 16)) & 0xFFFF; }

[[noreturn]] void fail(uint64_t n, const char* fmt, ...) {
    std::fprintf(stderr, "MISMATCH at instruction %llu (cycle %llu): ",
                 (unsigned long long)n, (unsigned long long)cycles);
    va_list ap; va_start(ap, fmt); std::vfprintf(stderr, fmt, ap); va_end(ap);
    std::fprintf(stderr, "\nlast instructions (pc word):\n");
    for (auto& h : history) std::fprintf(stderr, "  %s\n", h.c_str());
    std::fprintf(stderr, "HDL registers:");
    for (int i = 0; i < 16; i++) std::fprintf(stderr, " %06o", reg(i));
    std::fprintf(stderr, " flags %02o\n", top->flags);
    std::exit(1);
}

}  // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    if (argc < 2) { std::fprintf(stderr, "usage: %s TRACE [max]\n", argv[0]); return 2; }
    uint64_t max_n = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : ~0ull;

    Trace t;
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) { std::perror(argv[1]); return 2; }
    for (int ch; (ch = std::fgetc(f)) != EOF;) t.b.push_back((uint8_t)ch);
    std::fclose(f);
    if (t.b.size() < 8 || std::memcmp(t.b.data(), "ABLT1\0\0\0", 8) != 0) {
        std::fprintf(stderr, "%s: not a lockstep trace\n", argv[1]);
        return 2;
    }
    t.p = 8;

    top = new Vable_sim_top;
    top->rst = 1;
    top->io_ack = top->io_nosyn = top->halt_req = 0;
    top->irq = 0;
    for (int i = 0; i < 16; i++) {
        top->dbg_we = 1; top->dbg_addr = i; top->dbg_wdata = t.u16(); tick();
    }
    top->dbg_addr = 16; top->dbg_wdata = t.u8(); tick();
    top->dbg_we = 0;
    for (int a = 0; a < 65536; a++) {
        top->ld_we = 1; top->ld_addr = a; top->ld_data = t.u16(); tick();
    }
    top->ld_we = 0;
    tick();
    top->rst = 0;
    cycles = 0;

    uint64_t n = 0;
    bool check_snapshot = false;
    uint16_t snap[16]; uint8_t snap_flags = 0;
    char buf[64];

    while (n < max_n) {
        top->clk = 0; top->eval();           // outputs for the current state
        top->io_ack = top->io_nosyn = 0;
        top->irq = 0;

        if (check_snapshot) {                // state after the last instruction's END
            for (int i = 0; i < 16; i++)
                if (reg(i) != snap[i]) fail(n, "R%o = %06o, Python %06o", i, reg(i), snap[i]);
            if (top->flags != snap_flags) fail(n, "flags %02o, Python %02o", top->flags, snap_flags);
            check_snapshot = false;
        }
        if (top->halted) {
            if (t.peek() != 'H') fail(n, "HDL halted (reason %d), Python did not", top->halt_reason);
            t.u8();
            uint8_t why = t.u8();
            if (why != top->halt_reason) fail(n, "halt reason %d, Python %d", top->halt_reason, why);
            break;
        }
        if (t.peek() == 'E') break;

        if (top->irq_sample && top->irq_psw) {
            if (t.peek() != 'P') fail(n, "HDL reads the PSW, trace has '%c'", t.peek());
            t.u8(); top->irq = t.u16() >> 4;
        }
        if (top->io_rd) {
            uint8_t k = t.peek();
            if (k == 'H') top->io_nosyn = 1;
            else {
                if (k != 'R') fail(n, "HDL reads D%o, trace has '%c'", top->io_dev, k);
                t.u8();
                uint8_t dev = t.u8(); uint16_t v = t.u16();
                if (dev != top->io_dev) fail(n, "HDL reads D%o, Python D%o", top->io_dev, dev);
                top->io_rdata = v; top->io_ack = 1;
            }
        }
        if (top->io_wr) {
            uint8_t k = t.peek();
            if (k == 'H') top->io_nosyn = 1;
            else {
                if (k != 'W') fail(n, "HDL writes D%o = %06o, trace has '%c'", top->io_dev, top->io_wdata, k);
                t.u8();
                uint8_t dev = t.u8(); uint16_t v = t.u16();
                if (dev != top->io_dev || v != top->io_wdata)
                    fail(n, "HDL writes D%o = %06o, Python D%o = %06o", top->io_dev, top->io_wdata, dev, v);
                top->io_ack = 1;
            }
        }
        if (top->instr_done) {
            if (t.peek() == 'Q') { t.u8(); top->irq = t.u16() >> 4; }
            if (t.peek() != 'I') fail(n, "HDL completes %06o, trace has '%c'", top->instr_pc, t.peek());
            t.u8();
            uint16_t pc = t.u16(), w = t.u16();
            std::snprintf(buf, sizeof buf, "%06o %06o", top->instr_pc, top->instr_word);
            history.push_back(buf);
            if (history.size() > 16) history.pop_front();
            if (pc != top->instr_pc || w != top->instr_word)
                fail(n, "HDL completed %06o %06o, Python %06o %06o", top->instr_pc, top->instr_word, pc, w);
            n++;
            if (t.peek() == 'S') {
                t.u8();
                for (int i = 0; i < 16; i++) snap[i] = t.u16();
                snap_flags = t.u8();
                check_snapshot = true;
            }
        }
        top->clk = 1; top->eval();
        cycles++;
        if (cycles > 64 * (n + 1000)) fail(n, "HDL stuck (state does not advance)");
    }
    std::printf("lockstep OK: %llu instructions, %llu cycles\n",
                (unsigned long long)n, (unsigned long long)cycles);
    delete top;
    return 0;
}
