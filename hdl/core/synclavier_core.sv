// Synclavier II core, board-independent: able_system plus everything the
// MiSTer top (mister/Synclavier.sv) and the board simulation
// (hdl/sim/board_top.sv) share:
//   boot_loader   stands in for the boot ROM: loads MONITOR from F0, or a
//                 state image (tools/state_image.py, e.g. ORK-LM) from S2;
//   sd_floppy     F0/F1 floppy images and the state image on the SD block
//                 interface (hps_io, 3 drives);
//   term_display  the system terminal (D50) as 80 x 24 text on video;
//   ps2_ascii     the keyboard (hps_io ps2_key) as terminal input;
//   midi_in       MIDI (UART, MidiLink) to the original keyboard and panel;
//   midi_vpk      the same MIDI to the velocity keyboard when the state image
//                 selects it (SYN-5.3; able_system kb_vpk);
//   dev_midi      D70-D73 MIDI subsystem card when the state image has D51
//                 bit 8 (SYN-5.3): MIDI in through midi_card_feed (panel
//                 controls stay with the keyboard paths), MIDI out on midi_txd;
//   panel_mouse   the mouse: click the panel buttons shown on the screen.
// External memory (D60-D63: EXT_SECTORS sectors for a floppy boot, a
// state image's own size otherwise, at most 4096) is a word port (xr_*):
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
    input  logic        rt_voices,      // FM and poly voices on real time (voice_clock.sv, M14)
    input  logic        clk_vid,        // video: 25 MHz x VID_CE_DIV

    input  logic [10:0] ps2_key,
    input  logic [24:0] ps2_mouse,
    input  logic [1:0]  color,
    input  logic        panel_over,      // VT640 terminal: panel strip over its last 96 lines
    input  logic        stall_view,      // status line: lag by stall cause instead of health
    input  logic [13:0] hw_cfg,          // OSD Hardware page (M16): card complement, taken at reset

    input  logic [4:0]  img_mounted,
    input  logic        img_readonly,
    input  logic [63:0] img_size,
    output logic [31:0] sd_lba0,
    output logic [31:0] sd_lba1,
    output logic [31:0] sd_lba2,
    output logic [31:0] sd_lba3,
    output logic [31:0] sd_lba4,
    output logic [4:0]  sd_rd,
    output logic [4:0]  sd_wr,
    output logic [5:0]  sd_blk_cnt3,     // drives 3, 4 (SCSI disks): blocks - 1 per request
    output logic [5:0]  sd_blk_cnt4,
    input  logic [4:0]  sd_ack,
    input  logic [13:0] sd_buff_addr,
    input  logic [7:0]  sd_buff_dout,
    output logic [7:0]  sd_buff_din,
    input  logic        sd_buff_wr,

    output logic [26:0] xr_addr,         // words; poly memory from 0x1000000 (up to 224 MB)
    output logic        xr_rd,
    output logic        xr_wr,
    output logic        xr_wide,         // with xr_wr: all 4 words of the 64-bit word
    output logic [15:0] xr_wdata,
    input  logic [15:0] xr_rdata,
    input  logic        xr_ack,
    // poly mix reads (ddram_word's read stream): many in flight, data in order
    output logic [26:0] xs_addr,
    output logic        xs_rd,
    input  logic        xs_ack,
    input  logic        xs_rvalid,
    input  logic [15:0] xs_rdata,

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
    output logic        midi_txd,       // MIDI out (the card's), at the speed MIDI in runs at
    input  logic        mouse_host_we,  // a mouse packet (simulation; beats the PS/2 mouse)
    input  logic [2:0]  mouse_host_buttons,
    input  logic [15:0] mouse_host_dxy,  // {dX, dY}, 8-bit two's complement
    input  logic        midi_card_we,   // a byte into the card's input FIFO (simulation; beats MIDI)
    input  logic [7:0]  midi_card_byte,
    input  logic        kb_host_we,     // keyboard / panel words (simulation; beats MIDI)
    input  logic        kb_host_panel,
    input  logic [2:0]  kb_host_index,
    input  logic [15:0] kb_host_value,
    input  logic        vpk_host_we,    // velocity keyboard host ops (simulation; beats MIDI)
    input  logic [2:0]  vpk_host_op,
    input  logic [7:0]  vpk_host_addr,
    input  logic [7:0]  vpk_host_data,

    output logic        led_disk,
    output logic        booting,
    output logic        boot_error,
    output logic        halted,
    output logic        poly_clearing,  // poly memory clear after reset (simulation: not stuck)

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
    logic [26:0] m_addr;
    logic        m_rd, m_wr, m_ack;
    logic [15:0] m_wdata, m_rdata;
    logic [4:0]  sd_present;
    logic        w1_protect;
    logic [16:0] w1_blocks;
    logic [1:0]  fd_protect;
    logic        w0_protect;
    logic [12:0] state_blocks;
    logic [16:0] w0_blocks;
    wire  [1:0]  fd_present = sd_present[1:0];
    logic [10:0] fd_sectors0, fd_sectors1;
    logic        scsi_hint, scsi_line_ok;            // dev_scsi <-> sd_floppy (seek time)
    logic [15:0] scsi_hint_blk, scsi_probe_blk;
    logic        scsi_unit;
    sd_floppy media (
        .clk, .rst(rst_hard),
        .addr(m_addr), .rd(m_rd), .wr(m_wr), .wdata(m_wdata), .rdata(m_rdata), .ack(m_ack),
        .present(sd_present), .protect(fd_protect), .sectors0(fd_sectors0), .sectors1(fd_sectors1),
        .blocks2(state_blocks), .protect3(w0_protect), .blocks3(w0_blocks),
        .protect4(w1_protect), .blocks4(w1_blocks),
        .active(led_disk),
        .img_mounted, .img_readonly, .img_size, .sd_lba0, .sd_lba1, .sd_lba2, .sd_lba3, .sd_lba4,
        .sd_rd, .sd_wr, .sd_blk_cnt3, .sd_blk_cnt4, .sd_ack,
        .sd_buff_addr, .sd_buff_dout, .sd_buff_din, .sd_buff_wr,
        .hint(scsi_hint), .hint_drive(scsi_unit ? 3'd4 : 3'd3), .hint_blk(scsi_hint_blk),
        .probe_drive(scsi_unit ? 3'd4 : 3'd3), .probe_blk(scsi_probe_blk), .probe_hit(scsi_line_ok)
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
    logic [25:0] b_fd_addr;
    logic [1:0]  cpu_model;
    logic [15:0] cpu_d57, term_bits;
    logic [16:0] ext_sectors;
    logic        b_fd_rd, b_xm_wr, msg_valid;
    logic [23:0] b_xm_addr;
    logic [15:0] b_xm_wdata;
    logic [7:0]  msg_data;
    logic        poly_mono;
    boot_loader boot (
        .clk, .rst, .f0_present(fd_present[0]), .state_present(sd_present[2]),
        .floppy_ext_sectors(EXT_SECTORS), .ext_sectors, .cpu_model, .cpu_d57, .term_bits,
        .mono(hw_cfg[6]), .pvoice(poly_mono),
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
    logic        s_xm_rd, s_xm_wr, s_xm_ack;
    logic [15:0] s_xm_wdata;
    logic        dev_rd, dev_wr;
    logic [6:0]  dev_num;
    logic [15:0] dev_wdata;
    logic [15:0] kb_lights [8];
    logic [15:0] kb_display [3];
    logic        kb_vpk;
    logic [1:0]  vpk_lights [160];
    logic [7:0]  vpk_chars [32];
    logic [7:0]  vpk_dp [4];
    logic        v_we;
    logic [2:0]  v_op;
    logic [7:0]  v_addr, v_data;
    logic        kb_rx_valid;
    logic [7:0]  kb_rx_data;
    logic [31:0] lag_us;
    logic [23:0] stall_us [7];
    logic [10:0] poly_units;
    logic [2:0]  poly_bins;
    logic [5:0]  poly_last;
    logic        term_vt640, term_mouse;
    logic [19:0] scsi_block_ns;
    logic [25:0] scsi_seek_ns;
    logic        scsi_hold;
    logic        voice_tick;
    logic [9:0]  voice_tick_ns;

    able_system #(.CLK_HZ(CLK_HZ)) sys (
        .clk, .rst(cpu_rst), .rt_enable, .lag_us, .stall_us,
        .rt_voices, .dbg_stall(1'b0), .voice_tick, .voice_tick_ns,
        .cpu_model, .cpu_d57, .term_bits, .hw_cfg, .poly_units, .poly_bins, .poly_last, .term_vt640, .term_mouse, .scsi_block_ns, .scsi_seek_ns,
        .dev_rd, .dev_wr, .dev_num, .dev_wdata,
        .dev_rdata, .dev_ack, .dev_nosyn, .dev_hold(scsi_hold),           // SCSI disk time
        .dev_irq(12'(mouse_irq) << 6),                // PSW bit 10: D54 (mouse)
        .ext_sectors,
        .xm_addr(s_xm_addr), .xm_rd(s_xm_rd), .xm_wr(s_xm_wr), .xm_wdata(s_xm_wdata),
        .xm_rdata(xr_rdata), .xm_ack(s_xm_ack),
        .fd_present, .fd_protect, .fd_sectors0, .fd_sectors1,
        .fd_spt0(FD_SPT), .fd_spt1(FD_SPT), .fd_sides0(FD_SIDES), .fd_sides1(FD_SIDES),
        .fd_addr(s_fd_addr), .fd_rd(s_fd_rd), .fd_wr(s_fd_wr), .fd_wdata(s_fd_wdata),
        .fd_rdata(m_rdata), .fd_ack(m_ack && !scsi_m),
        .kb_host_we(kb_host_we || h_we),
        .kb_host_panel(kb_host_we ? kb_host_panel : h_panel),
        .kb_host_index(kb_host_we ? kb_host_index : h_index),
        .kb_host_value(kb_host_we ? kb_host_value : h_value),
        .kb_lights, .kb_display,
        .kb_vpk, .vpk_host_we(v_we), .vpk_host_op(v_op), .vpk_host_addr(v_addr),
        .vpk_host_data(v_data), .vpk_lights, .vpk_chars, .vpk_dp,
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

    // ------------------------------------------- devices outside able_system
    //   D24-D27 SCSI host with the W0 disk on SD drive 3, W1 on drive 4 (dev_scsi.sv)
    //   D154-D157 poly synth (dev_poly.sv); without D51's poly bit a stub:
    //     writes accepted, reads 0 ([HYP] SYN-5.3 writes D155 without checking D51's poly bit;
    //     sim/devices/stubs.py PolyNoVoices)
    // Any other device: no SYN (the CPU halts, as the real machine hangs).
    logic [15:0] dev_rdata, scsi_rdata, midi_rdata, mouse_rdata;
    logic        dev_ack, dev_nosyn, scsi_ack, midi_ack, mouse_ack, mouse_irq;
    // D44/D45/D54 mouse (dev_mouse.sv) from the PS/2 mouse, when the state
    // image has one (SYN-5.3 configured for it)
    logic        ps_q, m_we;
    logic signed [7:0] m_dx, m_dy;
    logic [2:0]  m_btn;
    wire  signed [8:0] ps_dx = {ps2_mouse[4], ps2_mouse[15:8]};
    wire  signed [8:0] ps_dy = {ps2_mouse[5], ps2_mouse[23:16]};
    always_ff @(posedge clk) begin
        ps_q <= ps2_mouse[24];
        m_we <= mouse_host_we || (ps2_mouse[24] != ps_q && !rst);
        if (mouse_host_we) begin
            m_btn <= mouse_host_buttons; m_dx <= mouse_host_dxy[15:8]; m_dy <= mouse_host_dxy[7:0];
        end else begin
            m_btn <= {ps2_mouse[0], ps2_mouse[2], ps2_mouse[1]};      // left, middle, right
            m_dx <= ps_dx > 9'sd127 ? 8'sd127 : ps_dx < -9'sd127 ? -8'sd127 : 8'(ps_dx);
            m_dy <= ps_dy > 9'sd127 ? 8'sd127 : ps_dy < -9'sd127 ? -8'sd127 : 8'(ps_dy);
        end
    end
    dev_mouse mouse_port (
        .clk, .rst(cpu_rst), .tick, .tick_ns,
        .sel(sel_mouse), .rd(dev_rd), .wr(dev_wr),
        .reg_sel(dev_num == 7'o044 ? 2'd0 : dev_num == 7'o045 ? 2'd1 : 2'd2),
        .wdata(dev_wdata), .rdata(mouse_rdata), .ack(mouse_ack), .irq(mouse_irq),
        .host_we(m_we && term_mouse), .host_dx(m_dx), .host_dy(m_dy), .host_buttons(m_btn)
    );
    logic [23:0] scsi_addr;
    logic        scsi_rd, scsi_wr;
    logic [15:0] scsi_wdata;
    wire  sel_scsi = (dev_rd || dev_wr) && dev_num[6:2] == 5'b00101;        // 024-027
    wire  sel_poly = (dev_rd || dev_wr) && dev_num[6:2] == 5'b11011;        // 154-157
    wire  sel_mouse = (dev_rd || dev_wr) && term_mouse &&
                      (dev_num == 7'o044 || dev_num == 7'o045 || dev_num == 7'o054);
    wire  card     = term_bits[8];                                         // D51: D70 exists
    wire  sel_midi = (dev_rd || dev_wr) && dev_num[6:2] == 5'b01110 && card; // 070-073
    dev_scsi #(.TARGET(4'd5), .TARGET1(4'd4)) scsi (
        .clk, .rst(cpu_rst), .tick, .tick_ns, .block_ns(scsi_block_ns), .hold(scsi_hold),
        .seek_ns(scsi_seek_ns), .hint(scsi_hint), .hint_blk(scsi_hint_blk),
        .probe_blk(scsi_probe_blk), .line_ok(scsi_line_ok), .line_wait(rt_enable),
        .sel(sel_scsi), .rd(dev_rd), .wr(dev_wr), .reg_sel(dev_num[1:0]),
        .wdata(dev_wdata), .rdata(scsi_rdata), .ack(scsi_ack),
        .present(sd_present[3]), .protect(w0_protect), .blocks(w0_blocks),
        .present1(sd_present[4]), .protect1(w1_protect), .blocks1(w1_blocks), .d_unit(scsi_unit),
        .d_addr(scsi_addr), .d_rd(scsi_rd), .d_wr(scsi_wr), .d_wdata(scsi_wdata),
        .d_rdata(m_rdata), .d_ack(m_ack && (scsi_rd || scsi_wr))
    );
    // D154-D157 poly synth (dev_poly.sv), on when D51 has the poly bit (a
    // state image made with poly voices); otherwise it answers as a stub
    logic [15:0] poly_rdata, p_wdata;
    logic        poly_ack, p_rd, p_wr, p_ack;
    logic [26:0] p_addr, p_saddr;
    logic        p_wide;
    logic        mix_valid;
    logic signed [15:0] mix_l, mix_r;
    dev_poly #(.MEM_BITS(27)) poly (
        .clk, .rst(cpu_rst), .enable(term_bits[10]), .bin_count(poly_bins), .size_units(poly_units),
        .last_voices(poly_last), .mono(poly_mono),
        .tick(voice_tick), .tick_ns(voice_tick_ns),
        .sel(sel_poly), .rd(dev_rd), .wr(dev_wr), .reg_sel(dev_num[1:0]), .wdata(dev_wdata),
        .rdata(poly_rdata), .ack(poly_ack),
        .m_addr(p_addr), .m_rd(p_rd), .m_wr(p_wr), .m_wide(p_wide), .m_wdata(p_wdata), .m_rdata(xr_rdata),
        .clearing(poly_clearing),
        .m_ack(p_ack),
        .s_addr(p_saddr), .s_rd(xs_rd), .s_ack(xs_ack), .s_rvalid(xs_rvalid), .s_rdata(xs_rdata),
        .mix_in_valid(pcm_valid), .mix_in_l(pcm_l), .mix_in_r(pcm_r),
        .mix_out_valid(mix_valid), .mix_out_l(mix_l), .mix_out_r(mix_r)
    );

    always_comb begin
        dev_rdata = 16'd0; dev_ack = 1'b0; dev_nosyn = 1'b0;
        if (sel_scsi)      begin dev_rdata = scsi_rdata; dev_ack = scsi_ack; end
        else if (sel_poly) begin dev_rdata = poly_rdata; dev_ack = poly_ack; end
        else if (sel_midi) begin dev_rdata = midi_rdata; dev_ack = midi_ack; end
        else if (sel_mouse) begin dev_rdata = mouse_rdata; dev_ack = mouse_ack; end
        else               dev_nosyn = dev_rd || dev_wr;
    end

    // the boot loader owns the floppy and external memory ports in reset;
    // then the SCSI disks (drives 3, 4) or the floppies:
    // dev_floppy: {drive, sector[9:0], word} -> {drive[2:0], block[15:0], word}
    wire scsi_m = scsi_rd || scsi_wr;
    assign m_addr   = cpu_rst ? {1'b0, b_fd_addr} : scsi_m ? {scsi_unit ? 3'd4 : 3'd3, scsi_addr}
                                          : {2'b00, s_fd_addr[18], 6'd0, s_fd_addr[17:0]};
    assign m_rd     = cpu_rst ? b_fd_rd   : (scsi_m ? scsi_rd : s_fd_rd);
    assign m_wr     = cpu_rst ? 1'b0      : (scsi_m ? scsi_wr : s_fd_wr);
    assign m_wdata  = scsi_m ? scsi_wdata : s_fd_wdata;
    // external memory port: the boot loader in reset; then D60-D63 and the
    // code cache (able_system) or poly memory (words 0x1000000 up), one
    // access at a time, granted while the port is free
    logic xb, xo;                                      // busy, owner (1 = poly)
    always_ff @(posedge clk) begin
        if (cpu_rst) xb <= 1'b0;
        else if (!xb) begin
            if (s_xm_rd || s_xm_wr) begin xb <= 1'b1; xo <= 1'b0; end
            else if (p_rd || p_wr) begin xb <= 1'b1; xo <= 1'b1; end
        end else if (xr_ack) xb <= 1'b0;
    end
    assign s_xm_ack = xr_ack && xb && !xo;
    assign p_ack    = xr_ack && xb && xo;
    assign xr_addr  = cpu_rst ? {3'b000, b_xm_addr} : xo ? 27'h1000000 + p_addr : {3'b000, s_xm_addr};
    assign xs_addr  = 27'h1000000 + p_saddr;
    assign xr_wide  = !cpu_rst && xb && xo && p_wide;
    assign xr_rd    = cpu_rst ? 1'b0      : xb && (xo ? p_rd : s_xm_rd);
    assign xr_wr    = cpu_rst ? b_xm_wr   : xb && (xo ? p_wr : s_xm_wr);
    assign xr_wdata = cpu_rst ? b_xm_wdata : xo ? p_wdata : s_xm_wdata;

    // to real time: a FIFO played at a steady 48 kHz (audio_fifo.sv)
    logic [15:0] underruns, overruns;
    audio_fifo #(.CLK_HZ(CLK_HZ)) to_real_time (
        .clk, .rst, .in_valid(mix_valid), .in_l(mix_l), .in_r(mix_r),
        .out_l(audio_l), .out_r(audio_r), .out_strobe(), .underruns, .overruns
    );

    // ----------------------------------------------------------------- MIDI
    logic        midi_we, midi_panel;
    logic [2:0]  midi_index;
    logic [15:0] midi_value;
    midi_in #(.CLK_HZ(CLK_HZ)) midi (
        .clk, .rst, .rxd(midi_rxd),
        .host_we(midi_we), .host_panel(midi_panel), .host_index(midi_index), .host_value(midi_value),
        .byte_valid(midi_byte), .byte_data(midi_data), .frame_err(midi_ferr), .alt(midi_alt),
        .msg_valid(midi_msg), .msg_kind(midi_kind), .msg_chan(midi_chan),
        .msg_m1(midi_m1), .msg_m2(midi_m2)
    );
    logic        midi_msg;
    logic [2:0]  midi_kind;
    logic [3:0]  midi_chan;
    logic [6:0]  midi_m1, midi_m2;
    logic        mv_we;
    logic [2:0]  mv_op;
    logic [7:0]  mv_addr, mv_data;
    // MIDI subsystem card (D51 bit 8): channel messages and real-time bytes
    // go to the card, except panel controls (card_panel) and program change,
    // which also take the keyboard paths
    logic        card_panel, card_in_valid, card_tx_valid, card_tx_ready;
    logic [7:0]  card_in_data, card_tx_data;
    midi_card_feed to_card (
        .clk, .rst, .vpk(kb_vpk),
        .msg_valid(midi_msg && card), .msg_kind(midi_kind), .msg_chan(midi_chan),
        .msg_m1(midi_m1), .msg_m2(midi_m2), .byte_valid(midi_byte && card), .byte_data(midi_data),
        .panel(card_panel), .out_valid(card_in_valid), .out_data(card_in_data)
    );
    dev_midi midi_card (
        .clk, .rst(cpu_rst), .sel(sel_midi), .rd(dev_rd), .wr(dev_wr), .reg_sel(dev_num[1:0]),
        .wdata(dev_wdata), .rdata(midi_rdata), .ack(midi_ack),
        .rx_valid(midi_card_we || card_in_valid), .rx_data(midi_card_we ? midi_card_byte : card_in_data),
        .tx_valid(card_tx_valid), .tx_data(card_tx_data), .tx_ready(card_tx_ready)
    );
    midi_uart_tx #(.CLK_HZ(CLK_HZ)) midi_out (
        .clk, .rst, .alt(midi_alt), .valid(card_tx_valid), .data(card_tx_data),
        .ready(card_tx_ready), .txd(midi_txd)
    );
    wire midi_keys = !card || card_panel || midi_kind == 3'd2;   // message also for the keyboard

    midi_vpk #(.CLK_HZ(CLK_HZ)) midi_to_vpk (
        .clk, .rst, .msg_valid(midi_msg && kb_vpk && midi_keys), .msg_kind(midi_kind), .msg_chan(midi_chan),
        .msg_m1(midi_m1), .msg_m2(midi_m2),
        .host_we(mv_we), .host_op(mv_op), .host_addr(mv_addr), .host_data(mv_data)
    );
    // for the status line: bytes received, the last one, framing errors
    logic        midi_byte, midi_ferr, midi_alt;
    logic [7:0]  midi_data, midi_last;
    logic [15:0] midi_count, midi_errs;
    always_ff @(posedge clk)
        if (rst) begin
            midi_count <= '0; midi_errs <= '0; midi_last <= '0;
        end else begin
            if (midi_byte) begin midi_count <= midi_count + 16'd1; midi_last <= midi_data; end
            if (midi_ferr) midi_errs <= midi_errs + 16'd1;
        end

    // ------------------------------------------------- mouse; host port mux
    logic        mouse_we, ptr_on;
    logic [2:0]  mouse_index;
    logic [15:0] mouse_value;
    logic [9:0]  ptr_x;
    logic [8:0]  ptr_y;
    logic        mouse_vpk_we, mouse_vpk_down;
    logic [7:0]  mouse_vpk_pbn;
    panel_mouse mouse (
        .clk, .rst, .ps2_mouse, .x(ptr_x), .y(ptr_y), .moved(ptr_on),
        .we(mouse_we), .index(mouse_index), .value(mouse_value),
        .vpk(kb_vpk), .vpk_we(mouse_vpk_we), .vpk_pbn(mouse_vpk_pbn), .vpk_down(mouse_vpk_down)
    );

    // Velocity keyboard host ops, one a clock: simulation, then MIDI, then a
    // mouse button change (held until sent).
    logic        mp_we, mp_down;
    logic [7:0]  mp_pbn;
    always_ff @(posedge clk) begin
        if (rst) mp_we <= 1'b0;
        else if (mouse_vpk_we) begin
            mp_we <= 1'b1; mp_pbn <= mouse_vpk_pbn; mp_down <= mouse_vpk_down;
        end else if (mp_we && !vpk_host_we && !mv_we) mp_we <= 1'b0;
    end
    always_comb begin
        v_we = vpk_host_we || mv_we || mp_we;
        if (vpk_host_we) begin
            v_op = vpk_host_op; v_addr = vpk_host_addr; v_data = vpk_host_data;
        end else if (mv_we) begin
            v_op = mv_op; v_addr = mv_addr; v_data = mv_data;
        end else begin
            v_op = 3'd2; v_addr = mp_pbn; v_data = {7'd0, mp_down};
        end
    end

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
            if (midi_we && !midi_panel && !card) begin           // clavier (not with the card)
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
    logic keypad_app;
    ps2_ascii keys (.clk, .rst, .ps2_key, .keypad_app, .valid(kb_rx_valid), .ascii(kb_rx_data));

    term_display #(.CE_DIV(VID_CE_DIV)) display (
        .clk, .rst, .vclk(clk_vid),
        .in_valid(cpu_rst ? msg_valid : term_tx_valid),
        .in_data(cpu_rst ? msg_data : term_tx_data),
        .color, .lights(kb_lights), .display(kb_display),
        .vpk(kb_vpk), .vpk_lights, .vpk_chars, .vt640(term_vt640), .panel_over,
        .ptr_on, .ptr_x, .ptr_y, .lag_us, .underruns, .overruns, .stall_view, .stall_us,
        .midi_count, .midi_last, .midi_errs, .midi_alt,
        .ce_pix, .r(vga_r), .g(vga_g), .b(vga_b), .hs(vga_hs), .vs(vga_vs),
        .hblank(vga_hblank), .vblank(vga_vblank),
        .peek_addr, .peek_data, .top_row, .keypad_app
    );
endmodule
