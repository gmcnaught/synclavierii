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
//   board_top (-DBOARD): the MiSTer core (synclavier_core) from power-on.
//     Nothing is loaded: the bench plays the HPS (the trace's floppies as
//     mounted SD images) and DDR3; the core's boot loader boots MONITOR
//     from F0; the state it leaves must equal the trace's start (memory,
//     external memory, registers), then the run is compared as for the
//     system. At the end the screen is printed (and LOCKSTEP_FRAME=path
//     writes one video frame as a PGM). LOCKSTEP_STATE=path mounts a state
//     image (tools/state_image.py) in S2: the boot loader loads that state
//     instead, and it must equal the trace's start the same way.
//
// Usage: V<top> TRACE [max_instructions]
// Exit 0 on full agreement, 1 on the first mismatch (with context).

#include <algorithm>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#include "verilated.h"
#if defined(BOARD)
#include "Vboard_top.h"
#include "Vboard_top___024root.h"
#include "Vboard_top_able_system.h"         // able_system's memory is public
#include "Vboard_top_board_top.h"
#include "Vboard_top_synclavier_core.h"
#include "Vboard_top_dev_fm.h"               // and the FM interface's wave memory
typedef Vboard_top Top;
#define SYSTEM_DEVICES 1
static const uint16_t INTERNAL_IRQ = 0400 | 0100;   // D3, D50/D51 (D100 has none)
#elif defined(SYSTEM)
#include "Vable_sys_top.h"
typedef Vable_sys_top Top;
#define SYSTEM_DEVICES 1
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


#ifdef BOARD
// ---------------------------------------------------------------- board
// HPS side of hps_io's SD block interface: one 512-byte block per request.
uint32_t lba_of(Top* top, int d) {
    return d == 0 ? top->sd_lba0 : d == 1 ? top->sd_lba1 : d == 2 ? top->sd_lba2 : top->sd_lba3;
}

struct SdModel {
    std::vector<uint8_t> img[4];                 // F0, F1, state image, W0 (SCSI)
    bool present[4] = {false, false, false, false}, prot[4] = {false, false, true, false};
    int drive = -1, phase = 0, wait = 0, i = 0;
    bool writing = false;
    uint64_t reads = 0, writes = 0;
    void step(Top* top) {
        top->sd_buff_wr = 0;
        if (wait > 0) { wait--; return; }
        switch (phase) {
        case 0:                                    // idle: pick a request
            for (int d = 0; d < 4; d++)
                if ((top->sd_rd | top->sd_wr) >> d & 1) {
                    drive = d; writing = top->sd_wr >> d & 1;
                    phase = 1; wait = 40; return;
                }
            return;
        case 1:
            top->sd_ack = 1 << drive; top->sd_buff_addr = 0; i = 0;
            phase = writing ? 3 : 2; wait = 4; return;
        case 2: {                                  // block -> FPGA
            uint32_t lba = lba_of(top, drive);
            size_t off = (size_t)lba * 512 + i;
            top->sd_buff_addr = i;
            top->sd_buff_dout = off < img[drive].size() ? img[drive][off] : 0;
            top->sd_buff_wr = 1;
            wait = 3;
            if (++i == 512) { phase = 4; reads++; }
            return; }
        case 3: {                                  // block <- FPGA
            top->sd_buff_addr = i; phase = 5; wait = 3; return; }
        case 5: {
            uint32_t lba = lba_of(top, drive);
            size_t off = (size_t)lba * 512 + i;
            if (off < img[drive].size()) img[drive][off] = top->sd_buff_din;
            if (++i == 512) { phase = 4; writes++; } else phase = 3;
            return; }
        case 4:
            top->sd_ack = 0; phase = 0; wait = 8; return;
        }
    }
} sd;

// DDR3 behind DDRAM_*: Avalon-MM, burst 1, BUSY now and then, reads
// answered after a latency.
struct DdrModel {
    std::vector<uint64_t> mem;
    uint32_t base = 0x30000000u >> 3;
    std::deque<std::pair<int, uint64_t>> reads;    // (cycles left, data)
    uint64_t n = 0;
    void step(Top* top) {
        n++;
        top->DDRAM_DOUT_READY = 0;
        if (!reads.empty() && --reads.front().first <= 0) {
            top->DDRAM_DOUT = reads.front().second;
            top->DDRAM_DOUT_READY = 1;
            reads.pop_front();
        }
        top->DDRAM_BUSY = (n % 7) == 3;            // accepted on a clock with BUSY low
        if (top->DDRAM_BUSY) return;
        uint32_t a = top->DDRAM_ADDR - base;
        if ((top->DDRAM_RD || top->DDRAM_WE) && a >= mem.size()) {
            std::fprintf(stderr, "DDR3 access outside the model: %08x\n", top->DDRAM_ADDR << 3);
            std::exit(1);
        }
        if (top->DDRAM_WE) {
            uint64_t m = 0;
            for (int b = 0; b < 8; b++) if (top->DDRAM_BE >> b & 1) m |= 0xFFull << (8 * b);
            mem[a] = (mem[a] & ~m) | (top->DDRAM_DIN & m);
        }
        if (top->DDRAM_RD) reads.emplace_back(12, mem[a]);
    }
    uint16_t word(uint32_t w) const { return mem[w >> 2] >> (16 * (w & 3)) & 0xFFFF; }
} ddr;

void models() {
    if (top->rst_hard) return;                     // HPS and DDR3 idle in reset
    sd.step(top); ddr.step(top);
}

void board_tick() {
    top->clk = 0; top->eval();
    models(); top->eval();
    top->clk = 1; top->eval();
    cycles++;
}

// Power-on, mount the trace's floppies, let the boot loader run; compare the
// state it leaves with the trace's start state.
void board_start(Trace& t, bool& audio_trace) {
    uint16_t want_regs[16];
    for (int i = 0; i < 16; i++) want_regs[i] = t.u16();
    uint8_t want_flags = t.u8();
    std::vector<uint16_t> want_mem(65536), want_xm;
    std::vector<uint8_t> want_wave(8192, 0);       // the header's wave-memory entries
    for (auto& w : want_mem) w = t.u16();
    for (;;) {
        uint8_t k = t.u8();
        if (k == 'B') break;
        if (k == 'X') {
            uint32_t sectors = t.u32();
            if (sectors > 8192) { std::fprintf(stderr, "board: external memory over 8192 sectors\n"); std::exit(2); }
            want_xm.resize(sectors * 256);
            for (auto& w : want_xm) w = t.u16();
            // not zero: the loader clears external memory, dev_poly poly sector 0;
            // the poly memory (16M words from 0x1000000) is covered too
            ddr.mem.assign(std::max<size_t>(sectors * 256 / 4, 0x2000000 / 4), 0x5A5A5A5A5A5A5A5Aull);
        } else if (k == 'F') {
            uint8_t drive = t.u8(); uint16_t sectors = t.u16();
            uint8_t spt = t.u8(), sides = t.u8(), prot = t.u8();
            if (spt != 5 || sides != 1) { std::fprintf(stderr, "board: floppies are 5 sectors x 1 side\n"); std::exit(2); }
            sd.present[drive] = true; sd.prot[drive] = prot;
            for (uint32_t a = 0; a < (uint32_t)sectors * 256; a++) {
                uint16_t w = t.u16();
                sd.img[drive].push_back(w >> 8); sd.img[drive].push_back(w & 0xFF);
            }
        } else if (k == 'O') {
            t.p += 8 + 2 + 1;
            uint8_t nch = t.u8();
            t.p += 4 * nch;
            audio_trace = true;
        } else if (k == 'C') {                     // Model C/D CPU state: not on the board yet
            t.p += 18;
        } else if (k == 'V') {                     // device state: loaded by the core itself
            uint8_t sel = t.u8(); uint16_t addr = t.u16(); uint32_t v = t.u32();
            if (sel == 6 && addr < 8192) want_wave[addr] = (uint8_t)v;
        } else { std::fprintf(stderr, "bad header section '%c'\n", k); std::exit(2); }
    }
    top->rst_hard = 1; top->rst = 1; top->rt_enable = 0;
    top->dev_ack = top->dev_nosyn = top->dev_hold = top->halt_req = 0;
    top->dev_irq = 0; top->ps2_key = 0; top->ps2_mouse = 0; top->img_mounted = 0;
    top->sd_ack = 0; top->sd_buff_wr = 0; top->DDRAM_BUSY = 0; top->DDRAM_DOUT_READY = 0;
    for (int i = 0; i < 8; i++) board_tick();
    // LOCKSTEP_STATE=path: a state image (tools/state_image.py) in S2, which
    // the boot loader then loads instead of booting MONITOR from F0
    if (const char* st = std::getenv("LOCKSTEP_STATE")) {
        FILE* f = std::fopen(st, "rb");
        if (!f) { std::perror(st); std::exit(2); }
        for (int ch; (ch = std::fgetc(f)) != EOF;) sd.img[2].push_back((uint8_t)ch);
        std::fclose(f);
        sd.present[2] = true;
    }
    // LOCKSTEP_W0=path: a SCSI disk image (W0, tools/w0_image.py) in S3
    if (const char* w0 = std::getenv("LOCKSTEP_W0")) {
        FILE* f = std::fopen(w0, "rb");
        if (!f) { std::perror(w0); std::exit(2); }
        for (int ch; (ch = std::fgetc(f)) != EOF;) sd.img[3].push_back((uint8_t)ch);
        std::fclose(f);
        sd.present[3] = true;
    }
    top->rst_hard = 0;
    for (int d = 0; d < 4; d++) if (sd.present[d]) {    // the HPS mounts the images
        top->img_mounted = 1 << d; top->img_size = sd.img[d].size(); top->img_readonly = sd.prot[d];
        board_tick();
        top->img_mounted = 0;
        board_tick();
    }
    for (int i = 0; i < 8; i++) board_tick();
    top->rst = 0;
    uint64_t boot_cycles = 0;
    while (top->booting) {
        board_tick();
        if (top->boot_error) { std::fprintf(stderr, "board: boot loader failed\n"); std::exit(1); }
        if (++boot_cycles > 200'000'000) { std::fprintf(stderr, "board: boot loader stuck\n"); std::exit(1); }
    }
    // compare with the trace's start state
    auto& mem = top->rootp->board_top->core->sys->mem;
    int bad = 0;
    for (int a = 0; a < 65536; a++)
        if (mem[a] != want_mem[a] && bad++ < 8)
            std::fprintf(stderr, "board: memory %06o = %06o, Python %06o\n", a, mem[a], want_mem[a]);
    auto& wave = top->rootp->board_top->core->sys->fm->wave;
    for (int a = 0; a < 8192; a++)
        if (wave[a] != want_wave[a] && bad++ < 12)
            std::fprintf(stderr, "board: wave memory %d = %d, Python %d\n", a, wave[a], want_wave[a]);
    for (size_t a = 0; a < want_xm.size(); a++)
        if (ddr.word(a) != want_xm[a] && bad++ < 16)
            std::fprintf(stderr, "board: external word %zu = %06o, Python %06o\n", a, ddr.word(a), want_xm[a]);
    top->clk = 0; top->eval();
    for (int i = 0; i < 16; i++)
        if (reg(i) != want_regs[i] && bad++ < 24)
            std::fprintf(stderr, "board: R%o = %06o, Python %06o\n", i, reg(i), want_regs[i]);
    if (top->flags != want_flags && bad++ < 25)
        std::fprintf(stderr, "board: flags %02o, Python %02o\n", top->flags, want_flags);
    if (bad) { std::fprintf(stderr, "board: boot state differs (%d)\n", bad); std::exit(1); }
    std::printf("board: boot loader done in %llu clocks (%llu SD reads); state matches\n",
                (unsigned long long)boot_cycles, (unsigned long long)sd.reads);
}

// The text on the screen (through the display's peek port), then one frame.
void board_screen() {
    std::vector<std::string> rows;
    for (int r = 0; r < 24; r++) {
        std::string line;
        for (int c = 0; c < 80; c++) {
            top->peek_addr = (((top->top_row + r) % 24) << 7) | c;
            board_tick(); board_tick();
            uint8_t ch = top->peek_data;
            line.push_back(ch >= 32 && ch < 127 ? (char)ch : '?');
        }
        while (!line.empty() && line.back() == ' ') line.pop_back();
        rows.push_back(line);
    }
    std::printf("screen:\n");
    for (auto& l : rows) std::printf("|%s\n", l.c_str());
    if (const char* path = std::getenv("LOCKSTEP_FRAME")) {
        // wait for a vertical blank to end, then take 640 x 480 pixels
        uint64_t guard = 0;
        while (!top->vga_vblank && guard++ < 4'000'000) board_tick();
        while (top->vga_vblank && guard++ < 4'000'000) board_tick();
        std::vector<uint8_t> px;
        int x = 0, lines = 0, width = -1;
        bool in_line = false;
        while (guard++ < 4'000'000) {
            top->clk = 0; top->eval();
            models(); top->eval();
            if (top->ce_pix) {
                if (top->vga_vblank) break;
                if (!top->vga_hblank) { px.push_back(top->vga_g); x++; in_line = true; }
                else if (in_line) {
                    if (width < 0) width = x;
                    if (x != width) { std::fprintf(stderr, "board: line %d has %d pixels\n", lines, x); std::exit(1); }
                    lines++; x = 0; in_line = false;
                }
            }
            top->clk = 1; top->eval();
            cycles++;
        }
        FILE* f = std::fopen(path, "wb");
        if (!f) { std::perror(path); std::exit(2); }
        std::fprintf(f, "P5\n%d %d\n255\n", width, lines);
        std::fwrite(px.data(), 1, (size_t)width * lines, f);
        std::fclose(f);
        std::printf("frame: %d x %d -> %s\n", width, lines, path);
    }
}
#endif

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

#ifdef BOARD
    // power up with random contents everywhere (registers and memories), as
    // after a user reset on the board: the boot loader must set all of it
    Verilated::randReset(2);
#endif
    top = new Top;
#ifdef BOARD
    bool realtime = false, audio_trace = false;
    board_start(t, audio_trace);
    cycles = 0;
#else
    top->rst = 1;
#ifdef SYSTEM
    // LOCKSTEP_REALTIME=1: run with the throttle on; behaviour must not
    // change, and simulated time must track 20 ns clocks (50 MHz)
    bool realtime = std::getenv("LOCKSTEP_REALTIME") != nullptr;
    top->rt_enable = realtime;
#endif
    top->dev_ack = top->dev_nosyn = top->dev_hold = top->halt_req = 0;
    top->dev_irq = 0;
    top->cpu_model = 1; top->cpu_d57 = 0;          // Model B unless the trace says ('C')
#ifdef SYSTEM
    top->fd_present = top->fd_protect = 0;
    top->term_bits = 01000;                        // D60 present
#endif
    for (int i = 0; i < 16; i++) {
        top->dbg_we = 1; top->dbg_addr = i; top->dbg_wdata = t.u16(); tick();
    }
    top->dbg_addr = 16; top->dbg_wdata = t.u8(); tick();
    for (int i = 17; i <= 23; i++) {               // Model C/D state: zero unless 'C' says
        top->dbg_addr = i; top->dbg_wdata = 0; tick();
    }
    top->dbg_we = 0;
    for (int a = 0; a < 65536; a++) {
        top->ld_mem_we = 1; top->ld_mem_addr = a; top->ld_mem_data = t.u16(); tick();
    }
    top->ld_mem_we = 0;
    bool system_state = false, audio_trace = false;
    for (;;) {                                     // header sections up to 'B'
        uint8_t k = t.u8();
        if (k == 'B') break;
        if (k == 'X') {                            // external memory
            uint32_t sectors = t.u32();
            if (sectors > 8192) { std::fprintf(stderr, "external memory > 8192 sectors\n"); return 2; }
#ifdef SYSTEM
            top->ext_sectors = sectors;
#endif
            for (uint32_t a = 0; a < sectors * 256; a++) {
                top->ld_xm_we = 1; top->ld_xm_addr = a; top->ld_xm_data = t.u16(); tick();
            }
            top->ld_xm_we = 0;
        } else if (k == 'C') {                     // Model C/D CPU state
            top->cpu_model = t.u8(); top->cpu_d57 = t.u16();
            uint16_t bits = t.u16();
#ifdef SYSTEM
            top->term_bits = bits;
#else
            (void)bits;
#endif
            top->dbg_we = 1;
            top->dbg_addr = 17; top->dbg_wdata = t.u16(); tick();             // page
            top->dbg_addr = 18; top->dbg_wdata = t.u16(); tick();             // ppc
            { uint8_t nx = t.u8(), left = t.u8();
              top->dbg_addr = 19; top->dbg_wdata = (nx << 8) | left; tick(); }
            top->dbg_addr = 20; top->dbg_wdata = t.u16(); tick();             // repeat word
            top->dbg_addr = 21; top->dbg_wdata = t.u16(); tick();             // repeat pc
            top->dbg_addr = 22; top->dbg_wdata = t.u16(); tick();             // D2
            top->dbg_addr = 23; top->dbg_wdata = t.u8(); tick();              // shadow
            top->dbg_we = 0;
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
        } else if (k == 'O') {                     // voice engine state
            uint64_t rr = t.u64(); uint16_t to_next = t.u16(); uint8_t phase = t.u8();
            uint8_t nch = t.u8();
            audio_trace = true;
#ifdef SYSTEM
            top->ld_voice_we = 1;
            top->ld_voice_addr = 32; top->ld_voice_data = rr; tick();
            top->ld_voice_addr = 33; top->ld_voice_data = ((uint64_t)phase << 14) | to_next; tick();
            top->ld_voice_we = 0;
            for (int c = 0; c < nch; c++) {             // device 5, index 32 + 16c + 9
                uint16_t acc = t.u16(); uint8_t pre = t.u8(), point = t.u8();
                top->ld_dev_we = 1; top->ld_dev_sel = 5; top->ld_dev_addr = 32 + 16 * c + 9;
                top->ld_dev_data = ((uint32_t)acc << 15) | ((uint32_t)pre << 8) | point;
                tick();
            }
            top->ld_dev_we = 0;
#else
            (void)rr; (void)to_next; (void)phase;
            t.p += (size_t)nch * 4;
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
    (void)system_state; (void)audio_trace;
#endif
    tick();
    top->rst = 0;
    cycles = 0;
#endif

    uint64_t n = 0, time_ns = 0;
    uint32_t held = 0;                 // held-read clocks in the current read
    bool check_snapshot = false;
    uint16_t snap[16]; uint8_t snap_flags = 0; uint64_t snap_time = 0;
    std::deque<uint8_t> rx;            // terminal input still to push
    std::deque<std::pair<int64_t, int64_t>> want_audio;   // Python samples not yet matched
    uint64_t samples = 0;
    std::vector<int16_t> pcm;          // 48 kHz stereo from pcm_out (LOCKSTEP_WAV)
    char buf[64];
#ifdef SYSTEM_DEVICES
    auto audio_check = [&](uint64_t at) {
        if (audio_trace && top->pcm_valid) {
            pcm.push_back((int16_t)top->pcm_l);
            pcm.push_back((int16_t)top->pcm_r);
        }
        if (!audio_trace || !top->audio_valid) return;     // no audio recorded
        int64_t l = top->audio_l, r = top->audio_r;
        if (l & (1ll << 39)) l -= 1ll << 40;          // 40-bit signed
        if (r & (1ll << 39)) r -= 1ll << 40;
        if (want_audio.empty()) {
            if (at == ~0ull) return;                   // after the trace: extra samples
            fail(at, "HDL audio sample %llu with none expected", (unsigned long long)samples);
        }
        auto w = want_audio.front();
        want_audio.pop_front();
        if (w.first != l || w.second != r)
            fail(at, "audio sample %llu: HDL (%lld, %lld), Python (%lld, %lld)",
                 (unsigned long long)samples, (long long)l, (long long)r,
                 (long long)w.first, (long long)w.second);
        samples++;
    };
#endif

    while (n < max_n) {
        top->clk = 0; top->eval();               // outputs for the current state
#ifdef BOARD
        models();
#endif
        while (t.peek() == 'A') {                // expected audio, in order
            t.u8();
            int64_t l = (int64_t)t.u64(), r = (int64_t)t.u64();
            want_audio.emplace_back(l, r);
        }
#ifdef SYSTEM_DEVICES
        audio_check(n);
#endif
        top->dev_ack = top->dev_nosyn = top->dev_hold = 0;
        top->dev_irq = 0;
#ifdef SYSTEM_DEVICES
        top->term_rx_valid = 0;
#endif

        if (check_snapshot) {                    // state after the last instruction's END
            for (int i = 0; i < 16; i++)
                if (reg(i) != snap[i]) fail(n, "R%o = %06o, Python %06o", i, reg(i), snap[i]);
            if (top->flags != snap_flags) fail(n, "flags %02o, Python %02o", top->flags, snap_flags);
#ifdef SYSTEM_DEVICES
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

#ifdef SYSTEM_DEVICES
        top->kb_host_we = 0;
        top->vpk_host_we = 0;
#ifdef BOARD
        top->midi_card_we = 0;
#endif
        if (t.peek() == 'K') {                   // host key/button change
            t.u8();
            uint8_t kind = t.u8(), index = t.u8();
            uint16_t value = t.u16();
            if (kind < 2) {                      // ORK: 0 clavier octave, 1 panel word
                top->kb_host_panel = kind; top->kb_host_index = index; top->kb_host_value = value;
                top->kb_host_we = 1;
            } else if (kind == 8) {              // a byte into the MIDI card's input FIFO
#ifdef BOARD
                top->midi_card_byte = value; top->midi_card_we = 1;
#else
                std::fprintf(stderr, "MIDI card bytes need the board top\n"); std::exit(2);
#endif
            } else {                             // VPK: op kind - 2 (dev_vpk.sv)
                top->vpk_host_op = kind - 2; top->vpk_host_addr = index; top->vpk_host_data = value;
                top->vpk_host_we = 1;
            }
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
#ifdef SYSTEM_DEVICES
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
#ifdef SYSTEM_DEVICES
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
        if (cycles > 64 * (n + 1000) + 64ull * held + time_ns / 10 || held > 10'000'000)
            fail(n, "HDL stuck (state does not advance)");
    }
#ifdef SYSTEM_DEVICES
    // the last samples finish mixing a few clocks after the trace ends
    for (int i = 0; i < 64; i++) {                 // (the engine runs on after a halt)
        top->dev_ack = top->dev_nosyn = top->dev_hold = 0;
        top->clk = 0; top->eval();
#ifdef BOARD
        models(); top->eval();
#endif
        audio_check(~0ull);
        top->clk = 1; top->eval();
    }
    if (!want_audio.empty())
        fail(n, "%zu Python audio samples not produced by the HDL", want_audio.size());
    if (const char* wav = std::getenv("LOCKSTEP_WAV")) {       // 16-bit stereo WAV
        FILE* w = std::fopen(wav, "wb");
        if (!w) { std::perror(wav); return 2; }
        uint32_t data = (uint32_t)pcm.size() * 2, rate = 48000;
        auto u32 = [&](uint32_t v) { std::fwrite(&v, 4, 1, w); };
        auto u16 = [&](uint16_t v) { std::fwrite(&v, 2, 1, w); };
        std::fwrite("RIFF", 1, 4, w); u32(36 + data); std::fwrite("WAVEfmt ", 1, 8, w);
        u32(16); u16(1); u16(2); u32(rate); u32(rate * 4); u16(4); u16(16);
        std::fwrite("data", 1, 4, w); u32(data);
        std::fwrite(pcm.data(), 2, pcm.size(), w);
        std::fclose(w);
    }
#endif
#ifdef SYSTEM_DEVICES
    if (realtime) {
        double real = cycles * 20.0, drift = (double)time_ns - real;
        std::printf("real time %.0f ns, simulated - real = %.0f ns\n", real, drift);
        if (drift > 2000 || drift < -210000) fail(n, "throttle drift %.0f ns", drift);   // CATCHUP_NS + 10 us
    }
#endif
#ifdef BOARD
    board_screen();
#endif
    std::printf("lockstep OK: %llu instructions, %llu cycles, %llu ns simulated",
                (unsigned long long)n, (unsigned long long)cycles, (unsigned long long)time_ns);
    if (samples) std::printf(", %llu audio samples", (unsigned long long)samples);
    std::printf("\n");
    delete top;
    return 0;
}
