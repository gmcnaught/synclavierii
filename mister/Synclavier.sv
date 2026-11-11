//============================================================================
//  Synclavier II (Model B ABLE computer, FM voices) for MiSTer.
//
//  The machine is hdl/core/synclavier_core.sv; this file connects it to the
//  MiSTer framework (sys/, Template_MiSTer, GPL-2.0): OSD and SD images
//  through hps_io, external memory in DDR3, terminal video, audio.
//
//  Use: mount a Release L system floppy image (e.g. 03-SYSTD, made with
//  tools/ned_disk.py --floppy) as F0, and optionally a data floppy as F1;
//  MONITOR boots from F0 and shows "Ready >" on the screen. MIDI (UART,
//  MidiLink) plays the original keyboard; see hdl/core/midi_in.sv.
//============================================================================

module emu
(
	`include "sys/emu_ports.vh"
);

assign ADC_BUS  = 'Z;
assign USER_OUT = '1;
assign {UART_RTS, UART_DTR} = 0;
wire   midi_txd;
assign UART_TXD = midi_txd;     // MIDI out: the MIDI subsystem card (D70), idle high otherwise
assign {SD_SCK, SD_MOSI, SD_CS} = 'Z;
assign {SDRAM_DQ, SDRAM_A, SDRAM_BA, SDRAM_CLK, SDRAM_CKE, SDRAM_DQML, SDRAM_DQMH, SDRAM_nWE, SDRAM_nCAS, SDRAM_nRAS, SDRAM_nCS} = 'Z;

assign VGA_SL = 0;
assign VGA_F1 = 0;
assign VGA_SCALER  = 0;
assign VGA_DISABLE = 0;
assign HDMI_FREEZE = 0;
assign HDMI_BLACKOUT = 0;
assign HDMI_BOB_DEINT = 0;

assign LED_DISK = {1'b1, led_disk};   // the core drives the disk LED
assign LED_POWER = 0;
assign BUTTONS = 0;

wire [1:0] ar = status[122:121];
assign VIDEO_ARX = (!ar) ? 12'd4 : (ar - 1'd1);
assign VIDEO_ARY = (!ar) ? 12'd3 : 12'd0;

`include "build_id.v"
localparam CONF_STR = {
	"Synclavier;UART31250,MIDI;",
	"-;",
	"S0,IMG,Floppy F0;",
	"S1,IMG,Floppy F1;",
	"S2,SST,State image;",
	"S3,IMG,SCSI disk W0;",
	"S4,IMG,SCSI disk W1;",
	"S5,STM,Digital STM source;",
	"S6,PRN,Printer capture;",
	"-;",
	"O[2:1],Text color,Green,Amber,White;",
	"O[122:121],Aspect ratio,Original,Full Screen,[ARC1],[ARC2];",
	"O[3],Real-time pacing,On,Off;",
	"O[4],VT640: panel strip,Hidden,Over bottom;",
	"O[5],Status line,Health,Lag by cause;",
	"O[6],Voice clock,Real time,CPU time;",
	"-;",
	"P1,Hardware (applies at reset);",
	"P1-,Cards of the instrument;",
	"P1O[12:7],Poly voices,From image,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,64,68,72,76,80,84,88,92,96,100,104,108,112,116,120,124,128;",
	"P1O[13],Poly voice cards,From image,Mono;",
	"P1O[17:14],Poly memory/bin,From image,4 MB,8 MB,12 MB,16 MB,20 MB,24 MB,28 MB,32 MB,224 MB/bins;",
	"P1O[20:18],FM voices,From image,8,16,24,32;",
	"P1O[21],Digital STM input (S5),From image,On;",
	"P1O[27],SMPTE reader (MTC in),From image,On;",
	"P1O[29],Printer (D40),From image,On;",
	"O[34:31],Outputs (multichannel),Stereo mix,1-2,3-4,5-6,7-8,9-10,11-12,13-14,15-16;",
	"P2,CRT Adjust;",
	"P2O[40],CRT Adjust,Off,On;",
	"H1P2O[45:41],CRT H-Size,0,+1,+2,+3,+4,+5,+6,+7,+8,+9,+10,-12,-11,-10,-9,-8,-7,-6,-5,-4,-3,-2,-1;",
	"H1P2O[49:46],CRT H-Position,0,+4,+8,+12,+16,+20,+24,+28,-32,-28,-24,-20,-16,-12,-8,-4;",
	"H1P2O[53:50],CRT V-Shift,0,+1,+2,+3,+4,+5,+6,+7,-8,-7,-6,-5,-4,-3,-2,-1;",
	"-;",
	"T[0],Reset;",
	"R[0],Reset and close OSD;",
	"I,Printout saved in S6,Printer: no file in S6 (lost),Printer: S6 file is full;",
	"v,0;",
	"V,v",`BUILD_DATE
};

wire   [1:0] buttons;
wire [127:0] status;
wire  [10:0] ps2_key;
wire  [24:0] ps2_mouse;

wire  [6:0] img_mounted;
wire        img_readonly;
wire [63:0] img_size;
wire [31:0] sd_lba0, sd_lba1, sd_lba2, sd_lba3, sd_lba4, sd_lba5, sd_lba6;
wire  [6:0] sd_rd, sd_wr, sd_ack;
wire [13:0] sd_buff_addr;
wire  [5:0] sd_blk_cnt3, sd_blk_cnt4, sd_blk_cnt5;
wire  [7:0] sd_buff_dout, sd_buff_din, sd_buff_din6;
wire        sd_buff_wr;
wire  [1:0] prn_note;
wire        prn_note_valid;

hps_io #(.CONF_STR(CONF_STR), .VDNUM(7)) hps_io
(
	.clk_sys(clk_sys),
	.HPS_BUS(HPS_BUS),
	.EXT_BUS(),
	.gamma_bus(),

	.buttons(buttons),
	.status(status),
	.status_menumask({14'd0, ~status[40], 1'b0}),   // H1: CRT Adjust items while On

	.ps2_key(ps2_key),
	.ps2_mouse(ps2_mouse),

	.img_mounted(img_mounted),
	.img_readonly(img_readonly),
	.img_size(img_size),
	.sd_lba('{sd_lba0, sd_lba1, sd_lba2, sd_lba3, sd_lba4, sd_lba5, sd_lba6}),
	.sd_blk_cnt('{6'd0, 6'd0, 6'd0, sd_blk_cnt3, sd_blk_cnt4, sd_blk_cnt5, 6'd0}),   // SCSI disks, STM source: 32-block reads
	.sd_rd(sd_rd),
	.sd_wr(sd_wr),
	.sd_ack(sd_ack),
	.sd_buff_addr(sd_buff_addr),
	.sd_buff_dout(sd_buff_dout),
	.sd_buff_din('{sd_buff_din, sd_buff_din, sd_buff_din, sd_buff_din, sd_buff_din, sd_buff_din, sd_buff_din6}),
	.sd_buff_wr(sd_buff_wr),

	.info_req(prn_note_valid),       // print capture: saved / lost / full (CONF_STR "I," 1-3)
	.info({6'd0, prn_note})
);

///////////////////////   CLOCKS   ///////////////////////////////

// rtl/pll: clk_sys 50 MHz (core; synclavier_core CLK_HZ must match),
// clk_vid 25 MHz (terminal video, 640 x 480)
wire clk_sys, clk_vid;
pll pll
(
	.refclk(CLK_50M),
	.rst(0),
	.outclk_0(clk_sys),
	.outclk_1(clk_vid)
);

reg rst_hard = 1, rst_user = 1;
always @(posedge clk_sys) begin
	rst_hard <= RESET;
	rst_user <= RESET | status[0] | buttons[1];
end

///////////////////////   CORE   /////////////////////////////////

wire [26:0] xr_addr;
wire        xr_rd, xr_wr, xr_wide, xr_ack;
wire [15:0] xr_wdata, xr_rdata;
wire [26:0] xs_addr;
wire        xs_rd, xs_ack, xs_rvalid;
wire [15:0] xs_rdata;
wire        ce_pix, hs, vs, hblank, vblank;
wire  [7:0] r, g, b;
wire        led_disk, booting, boot_error, halted;
wire signed [15:0] audio_l, audio_r;

synclavier_core #(.CLK_HZ(50_000_000), .VID_CE_DIV(1)) core
(
	.clk(clk_sys),
	.clk_vid(clk_vid),
	.rst_hard(rst_hard),
	.rst(rst_user),
	.rt_enable(~status[3]),
	.rt_voices(~status[3] & ~status[6]),

	.ps2_key(ps2_key),
	.ps2_mouse(ps2_mouse),
	.color(status[2:1]),
	.panel_over(status[4]),
	.stall_view(status[5]),
	.hw_cfg(status[20:7]),
	.dig_stm_on(status[21]),
	.smpte_osd(status[27]),
	.out_pair(status[34:31]),
	.printer_osd(status[29]),
	.readback_en(1'b1),

	.img_mounted(img_mounted),
	.img_readonly(img_readonly),
	.img_size(img_size),
	.sd_lba0(sd_lba0),
	.sd_lba1(sd_lba1),
	.sd_lba2(sd_lba2),
	.sd_lba3(sd_lba3),
	.sd_lba4(sd_lba4),
	.sd_lba5(sd_lba5),
	.sd_lba6(sd_lba6),
	.sd_rd(sd_rd),
	.sd_wr(sd_wr),
	.sd_blk_cnt3(sd_blk_cnt3),
	.sd_blk_cnt4(sd_blk_cnt4),
	.sd_blk_cnt5(sd_blk_cnt5),
	.sd_ack(sd_ack),
	.sd_buff_addr(sd_buff_addr),
	.sd_buff_dout(sd_buff_dout),
	.sd_buff_din(sd_buff_din),
	.sd_buff_din6(sd_buff_din6),
	.prn_note(prn_note),
	.prn_note_valid(prn_note_valid),
	.prn_count(),
	.prn_busy(),
	.sd_buff_wr(sd_buff_wr),

	.xr_addr(xr_addr),
	.xr_rd(xr_rd),
	.xr_wr(xr_wr),
	.xr_wide(xr_wide),
	.xr_wdata(xr_wdata),
	.xr_rdata(xr_rdata),
	.xr_ack(xr_ack),
	.xs_addr(xs_addr),
	.xs_rd(xs_rd),
	.xs_ack(xs_ack),
	.xs_rvalid(xs_rvalid),
	.xs_rdata(xs_rdata),

	.ce_pix(ce_pix),
	.vga_r(r),
	.vga_g(g),
	.vga_b(b),
	.vga_hs(hs),
	.vga_vs(vs),
	.vga_hblank(hblank),
	.vga_vblank(vblank),

	.audio_l(audio_l),
	.audio_r(audio_r),

	.midi_rxd(UART_RXD),
	.midi_txd(midi_txd),
	.mouse_host_we(1'b0),
	.mouse_host_buttons(3'd0),
	.mouse_host_dxy(16'd0),
	.midi_card_we(1'b0),
	.midi_card_byte(8'd0),
	.smpte_host_we(1'b0),
	.smpte_host_byte(8'd0),
	.kb_host_we(1'b0),
	.kb_host_panel(1'b0),
	.kb_host_index(3'd0),
	.kb_host_value(16'd0),
	.vpk_host_we(1'b0),
	.vpk_host_op(3'd0),
	.vpk_host_addr(8'd0),
	.vpk_host_data(8'd0),

	.led_disk(led_disk),
	.booting(booting),
	.boot_error(boot_error),
	.halted(halted),
	.poly_clearing(),

	.sim_rx_valid(1'b0),
	.sim_rx_data(8'd0),
	.term_tx_valid(),
	.term_tx_data(),
	.peek_addr(12'd0),
	.peek_data(),
	.top_row(),
	.instr_done(),
	.instr_pc(),
	.instr_word(),
	.regs_flat(),
	.flags(),
	.irq_sample(),
	.irq_psw(),
	.irq_all(),
	.io_held(),
	.tick(),
	.tick_ns(),
	.mon_valid(),
	.mon_wr(),
	.mon_dev(),
	.mon_data(),
	.halt_reason(),
	.pcm_valid(),
	.audio_valid(),
	.audio_sum_l(),
	.audio_sum_r()
);

assign DDRAM_CLK = clk_sys;
ddram_word ext_memory
(
	.clk(clk_sys),
	.rst(rst_hard),
	.addr(xr_addr),
	.rd(xr_rd),
	.wr(xr_wr),
	.wide(xr_wide),
	.wdata(xr_wdata),
	.rdata(xr_rdata),
	.ack(xr_ack),
	.s_addr(xs_addr),
	.s_rd(xs_rd),
	.s_ack(xs_ack),
	.s_rvalid(xs_rvalid),
	.s_rdata(xs_rdata),
	.DDRAM_BUSY(DDRAM_BUSY),
	.DDRAM_BURSTCNT(DDRAM_BURSTCNT),
	.DDRAM_ADDR(DDRAM_ADDR),
	.DDRAM_DOUT(DDRAM_DOUT),
	.DDRAM_DOUT_READY(DDRAM_DOUT_READY),
	.DDRAM_RD(DDRAM_RD),
	.DDRAM_DIN(DDRAM_DIN),
	.DDRAM_BE(DDRAM_BE),
	.DDRAM_WE(DDRAM_WE)
);

// CRT Adjust (OSD page 2): picture position (sync timing) and width (line
// resampling) for a CRT; Off is an exact passthrough (hdl/core/crt_adjust.sv).
// The settings are static; one register into the video clock.
reg  [13:0] crt_set;
always @(posedge clk_vid) crt_set <= status[53:40];
wire  [4:0] crt_hs_idx = crt_set[5:1];
wire signed [4:0] crt_hsize = (crt_hs_idx <= 5'd10) ? crt_hs_idx : (crt_hs_idx - 5'd23);
wire        c_hs, c_vs, c_hblank, c_vblank;
wire  [7:0] c_r, c_g, c_b;
crt_adjust crt
(
	.clk(clk_vid),
	.ce(ce_pix),
	.enable(crt_set[0]),
	.hsize(crt_hsize),
	.hpos(crt_set[9:6]),
	.vpos(crt_set[13:10]),
	.r_in(r), .g_in(g), .b_in(b),
	.hs_in(hs), .vs_in(vs), .hblank_in(hblank), .vblank_in(vblank),
	.r_out(c_r), .g_out(c_g), .b_out(c_b),
	.hs_out(c_hs), .vs_out(c_vs), .hblank_out(c_hblank), .vblank_out(c_vblank)
);

assign CLK_VIDEO = clk_vid;
assign CE_PIXEL  = ce_pix;
assign VGA_DE = ~(c_hblank | c_vblank);
assign VGA_HS = c_hs;
assign VGA_VS = c_vs;
assign VGA_R  = c_r;
assign VGA_G  = c_g;
assign VGA_B  = c_b;

assign AUDIO_S   = 1;
assign AUDIO_L   = audio_l;
assign AUDIO_R   = audio_r;
assign AUDIO_MIX = 0;

// slow blink: boot failed or the CPU halted (no SYN)
reg [24:0] blink;
always @(posedge clk_sys) blink <= blink + 1'd1;
assign LED_USER = (boot_error | halted) & blink[23];

endmodule
