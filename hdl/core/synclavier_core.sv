// Synclavier II core, board-independent: able_system plus everything the
// MiSTer top (mister/Synclavier.sv) and the board simulation
// (hdl/sim/board_top.sv) share:
//   boot_loader   stands in for the boot ROM: loads MONITOR from F0;
//   sd_floppy     F0/F1 floppy images on the SD block interface (hps_io);
//   term_display  the system terminal (D50) as 80 x 24 text on video;
//   ps2_ascii     the keyboard (hps_io ps2_key) as terminal input;
//   midi_in       MIDI (UART, MidiLink) to the original keyboard and panel;
//   panel_mouse   the mouse: click the panel buttons shown on the screen.
// External memory (D60-D63, EXT_SECTORS sectors) is a word port (xr_*):
// DDR3 on MiSTer (hdl/board/ddram_word.sv), a model in simulation.
// Devices not in the HDL answer no SYN, which halts the CPU as on the real
// machine.
module synclavier_core #(
    parameter longint CLK_HZ = 50_000_000,
    parameter int VID_CE_DIV = 2,                    // clk_vid cycles per pixel (MiSTer: 1, 25 MHz)
    parameter logic [16:0] EXT_SECTORS = 17'd1024,   // sim/system.py default
    parameter logic [3:0] FD_SPT = 4'd5,             // Release L F0/F1: 5 sectors per
    parameter logic [1:0] FD_SIDES = 2'd1            // track, single sided
) (
    input  logic        clk,
    input  logic        rst_hard,       // power-on: also forgets mounted images
    input  logic        rst,            // user reset: boot again
    input  logic        rt_enable,      // hold the CPU to real time
    input  logic        clk_vid,        // video: 25 MHz x VID_CE_DIV

    input  logic [10:0] ps2_key,
    input  logic [24:0] ps2_mouse,
    input  logic [1:0]  color,

    input  logic [1:0]  img_mounted,
    input  logic        img_readonly,
    input  logic [63:0] img_size,
    output logic [31:0] sd_lba0,
    output logic [31:0] sd_lba1,
    output logic [1:0]  sd_rd,
    output logic [1:0]  sd_wr,
    input  logic [1:0]  sd_ack,
    input  logic [8:0]  sd_buff_addr,
    input  logic [7:0]  sd_buff_dout,
    output logic [7:0]  sd_buff_din,
    input  logic        sd_buff_wr,

    output logic [23:0] xr_addr,
    output logic        xr_rd,
    output logic        xr_wr,
    output logic [15:0] xr_wdata,
    input  logic [15:0] xr_rdata,
    input  logic        xr_ack,

    output logic        ce_pix,
    output logic [7:0]  vga_r,
    output logic [7:0]  vga_g,
    output logic [7:0]  vga_b,
    output logic        vga_hs,
    output logic        vga_vs,
    output logic        vga_hblank,
    output logic        vga_vblank,

    output logic signed [15:0] audio_l,  // 48 kHz samples, held
    output logic signed [15:0] audio_r,

    input  logic        midi_rxd,       // MIDI in, 31250 baud (idle high)
    input  logic        kb_host_we,     // keyboard / panel words (simulation; beats MIDI)
    input  logic        kb_host_panel,
    input  logic [2:0]  kb_host_index,
    input  logic [15:0] kb_host_value,

    output logic        led_disk,
    output logic        booting,
    output logic        boot_error,
    output logic        halted,

    // simulation: terminal input beside the keyboard, observation
    input  logic        sim_rx_valid,
    input  logic [7:0]  sim_rx_data,
    output logic        term_tx_valid,
    output logic [7:0]  term_tx_data,
    input  logic [11:0] peek_addr,
    output logic [7:0]  peek_data,
    output logic [4:0]  top_row,
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
    output logic        mon_valid,
    output logic        mon_wr,
    output logic [6:0]  mon_dev,
    output logic [15:0] mon_data,
    output logic [1:0]  halt_reason,
    output logic        pcm_valid,
    output logic signed [15:0] pcm_l,
    output logic signed [15:0] pcm_r,
    output logic        audio_valid,
    output logic signed [39:0] audio_sum_l,
    output logic signed [39:0] audio_sum_r
);
    // ------------------------------------------------------------ floppies
    logic [18:0] m_addr;
    logic        m_rd, m_wr, m_ack;
    logic [15:0] m_wdata, m_rdata;
    logic [1:0]  fd_present, fd_protect;
    logic [10:0] fd_sectors0, fd_sectors1;
    sd_floppy media (
        .clk, .rst(rst_hard),
        .addr(m_addr), .rd(m_rd), .wr(m_wr), .wdata(m_wdata), .rdata(m_rdata), .ack(m_ack),
        .present(fd_present), .protect(fd_protect), .sectors0(fd_sectors0), .sectors1(fd_sectors1),
        .active(led_disk),
        .img_mounted, .img_readonly, .img_size, .sd_lba0, .sd_lba1, .sd_rd, .sd_wr, .sd_ack,
        .sd_buff_addr, .sd_buff_dout, .sd_buff_din, .sd_buff_wr
    );

    // ---------------------------------------------------------- boot loader
    logic        cpu_rst;
    logic        ld_dev_we, ld_voice_we, dbg_we, ld_mem_we;
    logic [2:0]  ld_dev_sel;
    logic [12:0] ld_dev_addr;
    logic [31:0] ld_dev_data;
    logic [5:0]  ld_voice_addr;
    logic [63:0] ld_voice_data;
    logic [4:0]  dbg_addr;
    logic [15:0] dbg_wdata, ld_mem_addr, ld_mem_data;
    logic [18:0] b_fd_addr;
    logic        b_fd_rd, b_xm_wr, msg_valid;
    logic [23:0] b_xm_addr;
    logic [15:0] b_xm_wdata;
    logic [7:0]  msg_data;
    boot_loader boot (
        .clk, .rst, .f0_present(fd_present[0]), .ext_sectors(EXT_SECTORS),
        .cpu_rst, .error(boot_error),
        .ld_dev_we, .ld_dev_sel, .ld_dev_addr, .ld_dev_data,
        .ld_voice_we, .ld_voice_addr, .ld_voice_data,
        .dbg_we, .dbg_addr, .dbg_wdata, .ld_mem_we, .ld_mem_addr, .ld_mem_data,
        .fd_addr(b_fd_addr), .fd_rd(b_fd_rd), .fd_rdata(m_rdata), .fd_ack(m_ack),
        .xm_addr(b_xm_addr), .xm_wr(b_xm_wr), .xm_wdata(b_xm_wdata), .xm_ack(xr_ack),
        .msg_valid, .msg_data
    );
    assign booting = cpu_rst;

    // --------------------------------------------------------------- system
    logic [18:0] s_fd_addr;
    logic        s_fd_rd, s_fd_wr;
    logic [15:0] s_fd_wdata;
    logic [23:0] s_xm_addr;
    logic        s_xm_rd, s_xm_wr;
    logic [15:0] s_xm_wdata;
    logic        dev_rd, dev_wr;
    logic [6:0]  dev_num;
    logic [15:0] dev_wdata;
    logic [15:0] kb_lights [8];
    logic [15:0] kb_display [3];
    logic        kb_rx_valid;
    logic [7:0]  kb_rx_data;

    able_system #(.CLK_HZ(CLK_HZ)) sys (
        .clk, .rst(cpu_rst), .rt_enable,
        .dev_rd, .dev_wr, .dev_num, .dev_wdata,
        .dev_rdata(16'd0), .dev_ack(1'b0), .dev_nosyn(dev_rd || dev_wr), .dev_hold(1'b0),
        .dev_irq(12'd0),
        .ext_sectors(EXT_SECTORS),
        .xm_addr(s_xm_addr), .xm_rd(s_xm_rd), .xm_wr(s_xm_wr), .xm_wdata(s_xm_wdata),
        .xm_rdata(xr_rdata), .xm_ack(xr_ack),
        .fd_present, .fd_protect, .fd_sectors0, .fd_sectors1,
        .fd_spt0(FD_SPT), .fd_spt1(FD_SPT), .fd_sides0(FD_SIDES), .fd_sides1(FD_SIDES),
        .fd_addr(s_fd_addr), .fd_rd(s_fd_rd), .fd_wr(s_fd_wr), .fd_wdata(s_fd_wdata),
        .fd_rdata(m_rdata), .fd_ack(m_ack),
        .kb_host_we(kb_host_we || h_we),
        .kb_host_panel(kb_host_we ? kb_host_panel : h_panel),
        .kb_host_index(kb_host_we ? kb_host_index : h_index),
        .kb_host_value(kb_host_we ? kb_host_value : h_value),
        .kb_lights, .kb_display,
        .audio_valid, .audio_l(audio_sum_l), .audio_r(audio_sum_r),
        .pcm_valid, .pcm_l, .pcm_r,
        .ld_voice_we, .ld_voice_addr, .ld_voice_data,
        .term_rx_valid(kb_rx_valid || sim_rx_valid),
        .term_rx_data(sim_rx_valid ? sim_rx_data : kb_rx_data),
        .term_tx_valid, .term_tx_data,
        .halt_req(1'b0), .halted, .halt_reason,
        .ld_mem_we, .ld_mem_addr, .ld_mem_data, .dbg_we, .dbg_addr, .dbg_wdata,
        .ld_dev_we, .ld_dev_sel, .ld_dev_addr, .ld_dev_data,
        .instr_done, .instr_pc, .instr_word, .regs_flat, .flags, .irq_sample, .irq_psw,
        .irq_all, .io_held, .tick, .tick_ns, .mon_valid, .mon_wr, .mon_dev, .mon_data
    );

    // the boot loader owns the floppy and external memory ports in reset
    assign m_addr   = cpu_rst ? b_fd_addr : s_fd_addr;
    assign m_rd     = cpu_rst ? b_fd_rd   : s_fd_rd;
    assign m_wr     = cpu_rst ? 1'b0      : s_fd_wr;
    assign m_wdata  = s_fd_wdata;
    assign xr_addr  = cpu_rst ? b_xm_addr : s_xm_addr;
    assign xr_rd    = cpu_rst ? 1'b0      : s_xm_rd;
    assign xr_wr    = cpu_rst ? b_xm_wr   : s_xm_wr;
    assign xr_wdata = cpu_rst ? b_xm_wdata : s_xm_wdata;

    always_ff @(posedge clk) begin
        if (rst) begin
            audio_l <= '0;
            audio_r <= '0;
        end else if (pcm_valid) begin
            audio_l <= pcm_l;
            audio_r <= pcm_r;
        end
    end

    // ----------------------------------------------------------------- MIDI
    logic        midi_we, midi_panel;
    logic [2:0]  midi_index;
    logic [15:0] midi_value;
    midi_in #(.CLK_HZ(CLK_HZ)) midi (
        .clk, .rst, .rxd(midi_rxd),
        .host_we(midi_we), .host_panel(midi_panel), .host_index(midi_index), .host_value(midi_value),
        .byte_valid(), .byte_data()
    );

    // ------------------------------------------------- mouse; host port mux
    logic        mouse_we, ptr_on;
    logic [2:0]  mouse_index;
    logic [15:0] mouse_value;
    logic [9:0]  ptr_x;
    logic [8:0]  ptr_y;
    panel_mouse mouse (
        .clk, .rst, .ps2_mouse, .x(ptr_x), .y(ptr_y), .moved(ptr_on),
        .we(mouse_we), .index(mouse_index), .value(mouse_value)
    );

    // Clavier words from MIDI go straight through. A panel button is down
    // while MIDI or the mouse holds it: each source's words are kept and the
    // OR of a changed word is written (one write a clock; MIDI first).
    logic [15:0] midi_pw [8], mouse_pw [8];
    logic [7:0]  pw_dirty;
    logic        h_we, h_panel;
    logic [2:0]  h_index, pw_i;
    logic [15:0] h_value;
    always_comb begin
        pw_i = 3'd0;
        for (int i = 7; i >= 0; i--) if (pw_dirty[i]) pw_i = 3'(i);
    end
    always_ff @(posedge clk) begin
        h_we <= 1'b0;
        if (rst) begin
            for (int i = 0; i < 8; i++) begin midi_pw[i] <= '0; mouse_pw[i] <= '0; end
            pw_dirty <= '0;
        end else begin
            if (midi_we && !midi_panel) begin                    // clavier
                h_we <= 1'b1; h_panel <= 1'b0; h_index <= midi_index; h_value <= midi_value;
            end else if (pw_dirty != '0) begin
                h_we <= 1'b1; h_panel <= 1'b1; h_index <= pw_i;
                h_value <= midi_pw[pw_i] | mouse_pw[pw_i];
                pw_dirty[pw_i] <= 1'b0;
            end
            if (midi_we && midi_panel) begin
                midi_pw[midi_index] <= midi_value;
                pw_dirty[midi_index] <= 1'b1;
            end
            if (mouse_we) begin
                mouse_pw[mouse_index] <= mouse_value;
                pw_dirty[mouse_index] <= 1'b1;
            end
        end
    end

    // ------------------------------------------------------ terminal, video
    ps2_ascii keys (.clk, .rst, .ps2_key, .valid(kb_rx_valid), .ascii(kb_rx_data));

    term_display #(.CE_DIV(VID_CE_DIV)) display (
        .clk, .rst, .vclk(clk_vid),
        .in_valid(cpu_rst ? msg_valid : term_tx_valid),
        .in_data(cpu_rst ? msg_data : term_tx_data),
        .color, .lights(kb_lights), .display(kb_display),
        .ptr_on, .ptr_x, .ptr_y,
        .ce_pix, .r(vga_r), .g(vga_g), .b(vga_b), .hs(vga_hs), .vs(vga_vs),
        .hblank(vga_hblank), .vblank(vga_vblank),
        .peek_addr, .peek_data, .top_row
    );
endmodule
