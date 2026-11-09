// ABLE system (M4.4/M4.5): CPU, 64K words of internal memory, and the
// devices ported to HDL so far:
//   D3 real-time clock, D4-D7 multiply/divide, D50/D51 terminal,
//   D60-D63 external memory (words in an external RAM behind xm_*),
//   D100-D104 floppy controller (floppy words in a RAM behind fd_*),
//   D130/D131 original keyboard and panel (key/button state from the host),
//   D160-D163 FM interface (registers, interpolators, wave memory),
//   D164/D165 control voltages (write-only),
// and the FM voice engine (in hdl/dev/dev_fm.sv) producing audio.
// Every other device number goes out on the dev_* port.
//
// Device time is the CPU's simulated time (333 ns per bus transfer, see
// able_cpu.sv), so device behaviour matches sim/devices/ exactly. On the
// board a throttle will hold the CPU to that time (risk R3).
module able_system #(
    parameter longint CLK_HZ = 50_000_000
) (
    input  logic        clk,
    input  logic        rst,
    input  logic [1:0]  cpu_model,         // 1 B, 2 C, 3 D (able_cpu.sv)
    input  logic [15:0] cpu_d57,           // Model D: D57 options
    input  logic [15:0] term_bits,         // D51 device-present bits (15-8)
    output logic [10:0] poly_units,        // poly memory size, 128 KB units (state load: device 3 index 8)
    input  logic        rt_enable,         // 1: hold the CPU to real time (throttle.sv)
    output logic [31:0] lag_us,            // real time given up by the throttle

    // devices outside this module
    output logic        dev_rd,
    output logic        dev_wr,
    output logic [6:0]  dev_num,
    output logic [15:0] dev_wdata,
    input  logic [15:0] dev_rdata,
    input  logic        dev_ack,
    input  logic        dev_nosyn,
    input  logic        dev_hold,
    input  logic [15:4] dev_irq,

    // external memory RAM (D60-D63)
    input  logic [16:0] ext_sectors,
    output logic [23:0] xm_addr,
    output logic        xm_rd,
    output logic        xm_wr,
    output logic [15:0] xm_wdata,
    input  logic [15:0] xm_rdata,
    input  logic        xm_ack,

    // floppy media (D100): presence, geometry and a word RAM
    input  logic [1:0]  fd_present,
    input  logic [1:0]  fd_protect,
    input  logic [10:0] fd_sectors0,
    input  logic [10:0] fd_sectors1,
    input  logic [3:0]  fd_spt0,
    input  logic [3:0]  fd_spt1,
    input  logic [1:0]  fd_sides0,
    input  logic [1:0]  fd_sides1,
    output logic [18:0] fd_addr,
    output logic        fd_rd,
    output logic        fd_wr,
    output logic [15:0] fd_wdata,
    input  logic [15:0] fd_rdata,
    input  logic        fd_ack,

    // keyboard/panel, host side
    input  logic        kb_host_we,
    input  logic        kb_host_panel,
    input  logic [2:0]  kb_host_index,
    input  logic [15:0] kb_host_value,
    output logic [15:0] kb_lights [8],
    output logic [15:0] kb_display [3],
    // velocity/pressure keyboard (dev_vpk.sv) in place of the ORK when kb_vpk
    // (load port: device 7 index 30), host side
    output logic        kb_vpk,
    input  logic        vpk_host_we,
    input  logic [2:0]  vpk_host_op,
    input  logic [7:0]  vpk_host_addr,
    input  logic [7:0]  vpk_host_data,
    output logic [1:0]  vpk_lights [160],
    output logic [7:0]  vpk_chars [32],
    output logic [7:0]  vpk_dp [4],

    // audio: one sample (sums over the voices) per 1/192000 s of simulated time
    output logic        audio_valid,
    output logic signed [39:0] audio_l,
    output logic signed [39:0] audio_r,
    output logic        pcm_valid,         // 48 kHz 16-bit stereo (pcm_out.sv)
    output logic signed [15:0] pcm_l,
    output logic signed [15:0] pcm_r,
    input  logic        ld_voice_we,       // voice engine state (simulation)
    input  logic [5:0]  ld_voice_addr,
    input  logic [63:0] ld_voice_data,

    // terminal, host side
    input  logic        term_rx_valid,
    input  logic [7:0]  term_rx_data,
    output logic        term_tx_valid,
    output logic [7:0]  term_tx_data,

    input  logic        halt_req,
    output logic        halted,
    output logic [1:0]  halt_reason,

    // simulation/debug: loads while in reset, observation
    input  logic        ld_mem_we,
    input  logic [15:0] ld_mem_addr,
    input  logic [15:0] ld_mem_data,
    input  logic        dbg_we,
    input  logic [4:0]  dbg_addr,
    input  logic [15:0] dbg_wdata,
    input  logic        ld_dev_we,         // device state: ld_dev_sel 0 rtc, 1 muldiv,
    input  logic [2:0]  ld_dev_sel,        // 2 extmem, 3 terminal, 4 floppy, 5 FM,
    input  logic [12:0] ld_dev_addr,       // 6 wave memory byte, 7 keyboard
    input  logic [31:0] ld_dev_data,
    output logic        instr_done,
    output logic [15:0] instr_pc,
    output logic [15:0] instr_word,
    output logic [255:0] regs_flat,
    output logic [4:0]  flags,
    output logic        irq_sample,
    output logic        irq_psw,
    output logic [15:4] irq_all,
    output logic        io_held,
    output logic        tick,
    output logic [9:0]  tick_ns,
    output logic        mon_valid,         // an I/O transfer completes this clock
    output logic        mon_wr,
    output logic [6:0]  mon_dev,
    output logic [15:0] mon_data
);
    // ------------------------------------------------------------ memory
    logic [15:0] mem [65536] /* verilator public */;   // public: board bench reads it
    logic [15:0] mem_addr, mem_wdata, mem_rdata;
    logic        mem_we;
    always_ff @(posedge clk) begin
        if (rst && ld_mem_we) mem[ld_mem_addr] <= ld_mem_data;
        else if (mem_we) mem[mem_addr] <= mem_wdata;
        mem_rdata <= mem[mem_addr];
    end

    // --------------------------------------------------------------- CPU
    logic        io_rd, io_wr, io_ack, io_nosyn, io_hold;
    logic [6:0]  io_dev;
    logic [15:0] io_wdata, io_rdata;
    logic [15:4] irq;
    logic        stall;

    logic        rt_stall, fm_stall;
    throttle #(.CLK_HZ(CLK_HZ)) pace (.clk, .rst, .enable(rt_enable), .tick, .tick_ns, .stall(rt_stall), .lag_us);
    assign stall = rt_stall || fm_stall;

    // Model D code fetches go through a cache (code_cache.sv) whose misses
    // share the external memory port with D60-D63 (the CPU does one or the
    // other at a time); D60-D63 writes also update the cache
    logic [23:0] cm_addr, cc_addr, x_addr;
    logic        cm_rd, cm_ack, cc_rd, x_rd, x_wr, x_ack;
    logic [15:0] cm_rdata, x_wdata;
    code_cache cache (
        .clk, .rst,
        .cm_addr, .cm_rd, .cm_rdata, .cm_ack,
        .wr_addr(x_addr), .wr_en(x_wr && x_ack), .wr_data(x_wdata),
        .m_addr(cc_addr), .m_rd(cc_rd), .m_rdata(xm_rdata), .m_ack(cc_rd && xm_ack)
    );
    assign xm_addr  = cc_rd ? cc_addr : x_addr;
    assign xm_rd    = cc_rd || x_rd;
    assign xm_wr    = !cc_rd && x_wr;
    assign xm_wdata = x_wdata;
    assign x_ack    = !cc_rd && xm_ack;

    able_cpu cpu (
        .clk, .rst, .model(cpu_model), .d57(cpu_d57),
        .cm_addr, .cm_rd, .cm_rdata, .cm_ack,
        .mem_addr, .mem_we, .mem_wdata, .mem_rdata,
        .io_rd, .io_wr, .io_dev, .io_wdata, .io_rdata, .io_ack, .io_nosyn, .io_hold,
        .io_held, .tick, .tick_ns,
        .irq, .irq_sample, .irq_psw,
        .stall, .halt_req, .halted, .halt_reason,
        .instr_done, .instr_pc, .instr_word,
        .dbg_we, .dbg_addr, .dbg_wdata, .regs_flat, .flags
    );

    // ----------------------------------------------------------- devices
    wire io = io_rd || io_wr;
    wire sel_rtc  = io && io_dev == 7'o003;
    wire sel_md   = io && io_dev[6:2] == 5'b00001;            // 004-007
    wire sel_term = io && io_dev[6:1] == 6'b010100;           // 050-051
    wire sel_xm   = io && io_dev[6:2] == 5'b01100;            // 060-063
    wire sel_fd   = io && io_dev >= 7'o100 && io_dev <= 7'o104;
    wire sel_kb   = io && io_dev[6:1] == 6'b101100;           // 130-131
    wire sel_fm   = io && io_dev[6:2] == 5'b11100;            // 160-163
    wire sel_cv   = io && io_dev[6:1] == 6'b111010;           // 164-165
    wire sel_ext  = io && !(sel_rtc || sel_md || sel_term || sel_xm || sel_fd ||
                            sel_kb || sel_fm || sel_cv);

    logic [15:0] rtc_rdata, md_rdata, term_rdata, xm_rdata_cpu, fd_rdata_cpu;
    logic        rtc_irq, md_ack, md_nosyn, term_ack, term_hold, term_irq, xm_cpu_ack;
    logic        fd_cpu_ack, fd_nosyn;
    logic [15:0] kb_rdata, fm_rdata;
    logic        kb_ack, kb_nosyn, fm_ack, fm_nosyn;
    logic        synth_strict;          // unknown D130/D131/D161/D162 reads: no SYN

    always_ff @(posedge clk)
        if (rst && ld_dev_we && ld_dev_sel == 3'd7 && ld_dev_addr == 13'd31)
            synth_strict <= ld_dev_data[0];
    logic rst_d;                            // ORK unless this reset's state load selects the VPK
    always_ff @(posedge clk) begin
        rst_d <= rst;
        // poly memory size: 32 MB (a 3200) unless the state load says
        if (rst && !rst_d) poly_units <= 11'd256;
        else if (rst && ld_dev_we && ld_dev_sel == 3'd3 && ld_dev_addr == 13'd8)
            poly_units <= ld_dev_data[10:0];
        if (rst && !rst_d) kb_vpk <= 1'b0;
        else if (rst && ld_dev_we && ld_dev_sel == 3'd7 && ld_dev_addr == 13'd30)
            kb_vpk <= ld_dev_data[0];
    end

    logic [15:0] ork_rdata, vpk_rdata;
    logic        ork_ack, ork_nosyn, vpk_ack, vpk_nosyn;
    assign kb_rdata = kb_vpk ? vpk_rdata : ork_rdata;
    assign kb_ack   = kb_vpk ? vpk_ack : ork_ack;
    assign kb_nosyn = kb_vpk ? vpk_nosyn : ork_nosyn;

    dev_vpk vpk (
        .clk, .rst, .sel(sel_kb && kb_vpk), .rd(io_rd), .wr(io_wr), .reg_sel(io_dev[0]),
        .wdata(io_wdata), .rdata(vpk_rdata), .ack(vpk_ack), .nosyn(vpk_nosyn), .strict(synth_strict),
        .host_we(vpk_host_we), .host_op(vpk_host_op), .host_addr(vpk_host_addr),
        .host_data(vpk_host_data), .lights(vpk_lights), .chars(vpk_chars), .dp(vpk_dp)
    );

    dev_keyboard keyboard (
        .clk, .rst, .sel(sel_kb && !kb_vpk), .rd(io_rd), .wr(io_wr), .reg_sel(io_dev[0]),
        .wdata(io_wdata), .rdata(ork_rdata), .ack(ork_ack), .nosyn(ork_nosyn), .strict(synth_strict),
        .host_we(kb_host_we), .host_panel(kb_host_panel), .host_index(kb_host_index),
        .host_value(kb_host_value), .lights(kb_lights), .display(kb_display),
        .ld_we(ld_dev_we && ld_dev_sel == 3'd7 && ld_dev_addr < 13'd27),
        .ld_addr(ld_dev_addr[4:0]), .ld_data(ld_dev_data)
    );

    // FM interface and voice engine (up to 32 voices; the number from the state image)
    dev_fm fm (
        .clk, .rst, .sel(sel_fm), .rd(io_rd), .wr(io_wr), .reg_sel(io_dev[1:0]),
        .wdata(io_wdata), .rdata(fm_rdata), .ack(fm_ack), .nosyn(fm_nosyn), .strict(synth_strict),
        .tick, .tick_ns, .stall(fm_stall),
        .audio_valid, .audio_l, .audio_r,
        .ld_we(ld_dev_we && (ld_dev_sel == 3'd5 || ld_dev_sel == 3'd6)),
        .ld_wave(ld_dev_sel == 3'd6), .ld_addr(ld_dev_addr), .ld_data(ld_dev_data),
        .ld_voice_we, .ld_voice_addr, .ld_voice_data
    );

    dev_rtc rtc (
        .clk, .rst, .acc(sel_rtc), .wr(io_wr), .rdata(rtc_rdata),
        .tick, .tick_ns, .irq(rtc_irq),
        .ld_we(ld_dev_we && ld_dev_sel == 3'd0), .ld_addr(ld_dev_addr[3:0]), .ld_data(ld_dev_data)
    );
    dev_muldiv muldiv (
        .clk, .rst, .sel(sel_md), .rd(io_rd), .wr(io_wr), .reg_sel(io_dev[1:0]),
        .wdata(io_wdata), .rdata(md_rdata), .ack(md_ack), .nosyn(md_nosyn),
        .ld_we(ld_dev_we && ld_dev_sel == 3'd1), .ld_addr(ld_dev_addr[3:0]), .ld_data(ld_dev_data)
    );
    dev_extmem extmem (
        .clk, .rst, .sel(sel_xm), .rd(io_rd), .wr(io_wr), .reg_sel(io_dev[1:0]),
        .wdata(io_wdata), .rdata(xm_rdata_cpu), .ack(xm_cpu_ack), .sectors(ext_sectors),
        .xm_addr(x_addr), .xm_rd(x_rd), .xm_wr(x_wr), .xm_wdata(x_wdata), .xm_rdata, .xm_ack(x_ack),
        .ld_we(ld_dev_we && ld_dev_sel == 3'd2), .ld_addr(ld_dev_addr[3:0]), .ld_data(ld_dev_data)
    );
    dev_terminal terminal (
        .clk, .rst, .device_bits(term_bits), .sel(sel_term), .rd(io_rd), .wr(io_wr), .reg_sel(io_dev[0]),
        .wdata(io_wdata), .rdata(term_rdata), .ack(term_ack), .hold(term_hold),
        .tick, .tick_ns, .irq(term_irq),
        .host_rx_valid(term_rx_valid), .host_rx_data(term_rx_data),
        .host_tx_valid(term_tx_valid), .host_tx_data(term_tx_data),
        .ld_we(ld_dev_we && ld_dev_sel == 3'd3 && ld_dev_addr < 13'd8), .ld_addr(ld_dev_addr[3:0]), .ld_data(ld_dev_data)
    );

    dev_floppy floppy (
        .clk, .rst, .sel(sel_fd), .rd(io_rd), .wr(io_wr), .reg_sel(io_dev[2:0]),
        .wdata(io_wdata), .rdata(fd_rdata_cpu), .ack(fd_cpu_ack), .nosyn(fd_nosyn),
        .tick, .tick_ns,
        .present(fd_present), .protect(fd_protect), .sectors0(fd_sectors0),
        .sectors1(fd_sectors1), .spt0(fd_spt0), .spt1(fd_spt1), .sides0(fd_sides0),
        .sides1(fd_sides1),
        .fd_addr, .fd_rd, .fd_wr, .fd_wdata, .fd_rdata, .fd_ack,
        .ld_we(ld_dev_we && ld_dev_sel == 3'd4), .ld_addr(ld_dev_addr[4:0]), .ld_data(ld_dev_data)
    );

    pcm_out pcm (
        .clk, .rst, .in_valid(audio_valid), .in_l(audio_l), .in_r(audio_r),
        .out_valid(pcm_valid), .out_l(pcm_l), .out_r(pcm_r)
    );

    assign dev_rd    = sel_ext && io_rd;
    assign dev_wr    = sel_ext && io_wr;
    assign dev_num   = io_dev;
    assign dev_wdata = io_wdata;

    always_comb begin
        io_rdata = dev_rdata;
        io_ack   = sel_ext && dev_ack;
        io_nosyn = sel_ext && dev_nosyn;
        io_hold  = sel_ext && dev_hold;
        if (sel_rtc)  begin io_rdata = rtc_rdata;    io_ack = 1'b1;       end
        if (sel_md)   begin io_rdata = md_rdata;     io_ack = md_ack;     io_nosyn = md_nosyn; end
        if (sel_term) begin io_rdata = term_rdata;   io_ack = term_ack;   io_hold = term_hold; end
        if (sel_xm)   begin io_rdata = xm_rdata_cpu; io_ack = xm_cpu_ack; end
        if (sel_fd)   begin io_rdata = fd_rdata_cpu; io_ack = fd_cpu_ack; io_nosyn = fd_nosyn; end
        if (sel_kb)   begin io_rdata = kb_rdata;     io_ack = kb_ack;     io_nosyn = kb_nosyn; end
        if (sel_fm)   begin io_rdata = fm_rdata;     io_ack = fm_ack;     io_nosyn = fm_nosyn; end
        if (sel_cv)   begin io_rdata = 16'd0;        io_ack = io_wr;      io_nosyn = io_rd;    end
    end

    // PSW bits 8 (D3) and 6 (D50/D51); bits of devices outside from dev_irq
    assign irq = dev_irq | {7'd0, rtc_irq, 1'b0, term_irq, 2'd0};    // bits 15-4
    assign irq_all = irq;

    assign mon_valid = io && io_ack && !io_nosyn;
    assign mon_wr    = io_wr;
    assign mon_dev   = io_dev;
    assign mon_data  = io_wr ? io_wdata : io_rdata;
endmodule
