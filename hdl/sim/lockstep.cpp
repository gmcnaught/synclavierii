// Lockstep check of the HDL against the Python simulator (M4.3-M4.5).
//
// Reads a trace written by sim/lockstep.py (format there) and runs one of
// two tops from the recorded state:
//   able_sim_top (default): the CPU alone; every device access is answered
//     from the trace.
//   able_sys_top (-DSYSTEM): able_system with the HDL devices (D3, D4-D7,
//     D50/D51, D60-D63, D100-D104, D130/D131, D160-D165); their reads,
//     writes, interrupt bits and timing are compared with the trace. Any
//     other device is answered from the trace.
// Each I/O transfer, PSW read, interrupt check and completed instruction
// must match; register snapshots (and, for the system, simulated time)
// are compared every 256 instructions.
//
// Usage: V<top> TRACE [max_instructions]
// Exit 0 on full agreement, 1 on the first mismatch (with context).

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#include "verilated.h"
#ifdef SYSTEM
#include "Vable_sys_top.h"
typedef Vable_sys_top Top;
static const uint16_t INTERNAL_IRQ = 0400 | 0100;   // D3, D50/D51 (D100 has none)
#else
#include "Vable_sim_top.h"
typedef Vable_sim_top Top;
static const uint16_t INTERNAL_IRQ = 0;
#endif

namespace {

struct Trace {
    std::vector<uint8_t> b;
    size_t p = 0;
    uint8_t u8() { return b[p++]; }
    uint16_t u16() { uint16_t v = b[p] | (b[p + 1] << 8); p += 2; return v; }
    uint32_t u32() { uint32_t v = u16(); return v | (uint32_t)u16() << 16; }
    uint64_t u64() { uint64_t v = u32(); return v | (uint64_t)u32() << 32; }
    uint8_t peek(size_t k = 0) const { return p + k >= b.size() ? 'E' : b[p + k]; }
    uint16_t peek16(size_t k) const { return b[p + k] | (b[p + k + 1] << 8); }
    uint32_t peek32(size_t k) const { return peek16(k) | (uint32_t)peek16(k + 2) << 16; }
};

Top* top;
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
    if (t.b.size() < 8 || std::memcmp(t.b.data(), "ABLT2\0\0\0", 8) != 0) {
        std::fprintf(stderr, "%s: not a lockstep trace (v2)\n", argv[1]);
        return 2;
    }
    t.p = 8;

    top = new Top;
    top->rst = 1;
    top->dev_ack = top->dev_nosyn = top->dev_hold = top->halt_req = 0;
    top->dev_irq = 0;
#ifdef SYSTEM
    top->fd_present = top->fd_protect = 0;
#endif
    for (int i = 0; i < 16; i++) {
        top->dbg_we = 1; top->dbg_addr = i; top->dbg_wdata = t.u16(); tick();
    }
    top->dbg_addr = 16; top->dbg_wdata = t.u8(); tick();
    top->dbg_we = 0;
    for (int a = 0; a < 65536; a++) {
        top->ld_mem_we = 1; top->ld_mem_addr = a; top->ld_mem_data = t.u16(); tick();
    }
    top->ld_mem_we = 0;
    bool system_state = false;
    for (;;) {                                     // header sections up to 'B'
        uint8_t k = t.u8();
        if (k == 'B') break;
        if (k == 'X') {                            // external memory
            uint32_t sectors = t.u32();
#ifdef SYSTEM
            if (sectors > 4096) { std::fprintf(stderr, "external memory > 4096 sectors\n"); return 2; }
            top->ext_sectors = sectors;
            for (uint32_t a = 0; a < sectors * 256; a++) {
                top->ld_xm_we = 1; top->ld_xm_addr = a; top->ld_xm_data = t.u16(); tick();
            }
            top->ld_xm_we = 0;
#else
            t.p += (size_t)sectors * 512;
#endif
        } else if (k == 'F') {                     // floppy media
            uint8_t drive = t.u8(); uint16_t sectors = t.u16();
            uint8_t spt = t.u8(), sides = t.u8(), prot = t.u8();
#ifdef SYSTEM
            if (sectors > 1024) { std::fprintf(stderr, "floppy > 1024 sectors\n"); return 2; }
            top->fd_present |= 1 << drive;
            if (prot) top->fd_protect |= 1 << drive;
            if (drive) { top->fd_sectors1 = sectors; top->fd_spt1 = spt; top->fd_sides1 = sides; }
            else       { top->fd_sectors0 = sectors; top->fd_spt0 = spt; top->fd_sides0 = sides; }
            for (uint32_t a = 0; a < (uint32_t)sectors * 256; a++) {
                top->ld_fd_we = 1; top->ld_fd_addr = (drive << 18) | a; top->ld_fd_data = t.u16(); tick();
            }
            top->ld_fd_we = 0;
#else
            (void)drive; (void)spt; (void)sides; (void)prot;
            t.p += (size_t)sectors * 512;
#endif
        } else if (k == 'V') {                     // device state
            uint8_t sel = t.u8(); uint16_t addr = t.u16(); uint32_t v = t.u32();
#ifdef SYSTEM
            top->ld_dev_we = 1; top->ld_dev_sel = sel; top->ld_dev_addr = addr;
            top->ld_dev_data = v; tick();
            top->ld_dev_we = 0;
#else
            (void)sel; (void)addr; (void)v;
#endif
            system_state = true;
        } else {
            std::fprintf(stderr, "bad header section '%c'\n", k);
            return 2;
        }
    }
#ifdef SYSTEM
    if (!system_state) { std::fprintf(stderr, "trace has no device state: record a system run\n"); return 2; }
#else
    (void)system_state;
#endif
    tick();
    top->rst = 0;
    cycles = 0;

    uint64_t n = 0, time_ns = 0;
    uint32_t held = 0;                 // held-read clocks in the current read
    bool check_snapshot = false;
    uint16_t snap[16]; uint8_t snap_flags = 0; uint64_t snap_time = 0;
    std::deque<uint8_t> rx;            // terminal input still to push
    char buf[64];

    while (n < max_n) {
        top->clk = 0; top->eval();               // outputs for the current state
        top->dev_ack = top->dev_nosyn = top->dev_hold = 0;
        top->dev_irq = 0;
#ifdef SYSTEM
        top->term_rx_valid = 0;
#endif

        if (check_snapshot) {                    // state after the last instruction's END
            for (int i = 0; i < 16; i++)
                if (reg(i) != snap[i]) fail(n, "R%o = %06o, Python %06o", i, reg(i), snap[i]);
            if (top->flags != snap_flags) fail(n, "flags %02o, Python %02o", top->flags, snap_flags);
#ifdef SYSTEM
            if (time_ns != snap_time)
                fail(n, "time %llu ns, Python %llu ns", (unsigned long long)time_ns,
                     (unsigned long long)snap_time);
#else
            (void)snap_time;
#endif
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

#ifdef SYSTEM
        top->kb_host_we = 0;
        if (t.peek() == 'K') {                   // host key/button change
            t.u8();
            top->kb_host_panel = t.u8(); top->kb_host_index = t.u8(); top->kb_host_value = t.u16();
            top->kb_host_we = 1;
        }
#else
        while (t.peek() == 'T' || t.peek() == 'K') {    // D50, D130 are replayed
            if (t.u8() == 'K') t.p += 4;
            else { t.u32(); t.p += t.u16(); }
        }
#endif
        // terminal input: pushed on the recorded held-read clock
        if (t.peek() == 'T') {
            uint32_t waits = t.peek32(1);
            if (waits == 0 || (top->io_held && held + 1 == waits)) {
                t.u8(); t.u32();
                uint16_t len = t.u16();
                for (int i = 0; i < len; i++) rx.push_back(t.u8());
                if (waits) held = (uint32_t)-1;          // +1 at this edge -> 0
            }
        }
#ifdef SYSTEM
        if (!rx.empty()) { top->term_rx_valid = 1; top->term_rx_data = rx.front(); rx.pop_front(); }
#else
        rx.clear();
#endif

        if (top->irq_sample && top->irq_psw) {
            if (t.peek() != 'P') fail(n, "HDL reads the PSW, trace has '%c'", t.peek());
            t.u8();
            uint16_t v = t.u16() >> 4;
            top->dev_irq = v & ~(INTERNAL_IRQ >> 4);
            top->eval();
            if ((top->irq_all & (INTERNAL_IRQ >> 4)) != (v & (INTERNAL_IRQ >> 4)))
                fail(n, "PSW interrupt bits %06o, Python %06o", top->irq_all << 4, v << 4);
        }
        // devices outside the HDL: answer from the trace (look ahead only;
        // the transfer is consumed below when it completes)
        size_t k = 0;
        uint32_t want_held = 0;
        if (t.peek() == 'w') { want_held = t.peek32(1); k = 5; }
        if (top->dev_rd) {
            uint8_t e = t.peek(k);
            if (e == 'H') top->dev_nosyn = 1;
            else if (e != 'R') fail(n, "HDL reads D%o, trace has '%c'", top->dev_num, e);
            else if (held < want_held) top->dev_hold = 1;
            else { top->dev_rdata = t.peek16(k + 2); top->dev_ack = 1; }
        }
        if (top->dev_wr) {
            uint8_t e = t.peek(k);
            if (e == 'H') top->dev_nosyn = 1;
            else if (e != 'W') fail(n, "HDL writes D%o = %06o, trace has '%c'", top->dev_num, top->dev_wdata, e);
            else top->dev_ack = 1;
        }
        top->eval();
        if (top->mon_valid) {                    // a transfer completes: compare
            uint32_t w = 0;
            if (t.peek() == 'w') { t.u8(); w = t.u32(); }
            uint8_t e = t.u8();
            if (e != (top->mon_wr ? 'W' : 'R'))
                fail(n, "HDL %s D%o = %06o, trace has '%c'", top->mon_wr ? "writes" : "reads",
                     top->mon_dev, top->mon_data, e);
            uint8_t dev = t.u8(); uint16_t v = t.u16();
            if (dev != top->mon_dev || v != top->mon_data)
                fail(n, "HDL %s D%o = %06o, Python D%o = %06o", top->mon_wr ? "writes" : "reads",
                     top->mon_dev, top->mon_data, dev, v);
#ifdef SYSTEM
            if (!top->mon_wr && w != held)
                fail(n, "read of D%o held %u clocks, Python %u steps", dev, held, w);
#else
            (void)w;
#endif
        }
        if (top->instr_done) {
            if (t.peek() == 'Q') {
                t.u8();
                uint16_t v = t.u16() >> 4;
                top->dev_irq = v & ~(INTERNAL_IRQ >> 4);
                top->eval();
                if ((top->irq_all & (INTERNAL_IRQ >> 4)) != (v & (INTERNAL_IRQ >> 4)))
                    fail(n, "interrupt bits %06o at the end, Python %06o", top->irq_all << 4, v << 4);
            }
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
                snap_time = t.u64();
                check_snapshot = true;
            }
        }
        bool was_held = top->io_held, was_tick = top->tick, done = top->instr_done;
        uint16_t ns = top->tick_ns;
        top->clk = 1; top->eval();
        cycles++;
        if (was_tick) time_ns += ns;
        if (was_held) held++;
        if (done) held = 0;
        if (cycles > 64 * (n + 1000) + 64ull * held || held > 10'000'000)
            fail(n, "HDL stuck (state does not advance)");
    }
    std::printf("lockstep OK: %llu instructions, %llu cycles, %llu ns simulated\n",
                (unsigned long long)n, (unsigned long long)cycles, (unsigned long long)time_ns);
    delete top;
    return 0;
}
