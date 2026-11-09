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
assign UART_TXD = 1;            // MIDI in only
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
	"-;",
	"O[2:1],Text color,Green,Amber,White;",
	"O[122:121],Aspect ratio,Original,Full Screen,[ARC1],[ARC2];",
	"O[3],Real-time pacing,On,Off;",
	"-;",
	"T[0],Reset;",
	"R[0],Reset and close OSD;",
	"v,0;",
	"V,v",`BUILD_DATE
};

wire   [1:0] buttons;
wire [127:0] status;
wire  [10:0] ps2_key;
wire  [24:0] ps2_mouse;

wire  [3:0] img_mounted;
wire        img_readonly;
wire [63:0] img_size;
wire [31:0] sd_lba0, sd_lba1, sd_lba2, sd_lba3;
wire  [3:0] sd_rd, sd_wr, sd_ack;
wire  [8:0] sd_buff_addr;
wire  [7:0] sd_buff_dout, sd_buff_din;
wire        sd_buff_wr;

hps_io #(.CONF_STR(CONF_STR), .VDNUM(4)) hps_io
(
	.clk_sys(clk_sys),
	.HPS_BUS(HPS_BUS),
	.EXT_BUS(),
	.gamma_bus(),

	.buttons(buttons),
	.status(status),
	.status_menumask(16'd0),

	.ps2_key(ps2_key),
	.ps2_mouse(ps2_mouse),

	.img_mounted(img_mounted),
	.img_readonly(img_readonly),
	.img_size(img_size),
	.sd_lba('{sd_lba0, sd_lba1, sd_lba2, sd_lba3}),
	.sd_blk_cnt('{6'd0, 6'd0, 6'd0, 6'd0}),
	.sd_rd(sd_rd),
	.sd_wr(sd_wr),
	.sd_ack(sd_ack),
	.sd_buff_addr(sd_buff_addr),
	.sd_buff_dout(sd_buff_dout),
	.sd_buff_din('{sd_buff_din, sd_buff_din, sd_buff_din, sd_buff_din}),
	.sd_buff_wr(sd_buff_wr)
);

///////////////////////   CLOCKS   ///////////////////////////////

// rtl/pll: clk_sys 16 MHz (core; synclavier_core CLK_HZ must match),
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

wire [25:0] xr_addr;
wire        xr_rd, xr_wr, xr_wide, xr_ack;
wire [15:0] xr_wdata, xr_rdata;
wire        ce_pix, hs, vs, hblank, vblank;
wire  [7:0] r, g, b;
wire        led_disk, booting, boot_error, halted;
wire signed [15:0] audio_l, audio_r;

synclavier_core #(.CLK_HZ(16_000_000), .VID_CE_DIV(1)) core
(
	.clk(clk_sys),
	.clk_vid(clk_vid),
	.rst_hard(rst_hard),
	.rst(rst_user),
	.rt_enable(~status[3]),

	.ps2_key(ps2_key),
	.ps2_mouse(ps2_mouse),
	.color(status[2:1]),

	.img_mounted(img_mounted),
	.img_readonly(img_readonly),
	.img_size(img_size),
	.sd_lba0(sd_lba0),
	.sd_lba1(sd_lba1),
	.sd_lba2(sd_lba2),
	.sd_lba3(sd_lba3),
	.sd_rd(sd_rd),
	.sd_wr(sd_wr),
	.sd_ack(sd_ack),
	.sd_buff_addr(sd_buff_addr),
	.sd_buff_dout(sd_buff_dout),
	.sd_buff_din(sd_buff_din),
	.sd_buff_wr(sd_buff_wr),

	.xr_addr(xr_addr),
	.xr_rd(xr_rd),
	.xr_wr(xr_wr),
	.xr_wide(xr_wide),
	.xr_wdata(xr_wdata),
	.xr_rdata(xr_rdata),
	.xr_ack(xr_ack),

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
	.kb_host_we(1'b0),
	.kb_host_panel(1'b0),
	.kb_host_index(3'd0),
	.kb_host_value(16'd0),

	.led_disk(led_disk),
	.booting(booting),
	.boot_error(boot_error),
	.halted(halted),

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

assign CLK_VIDEO = clk_vid;
assign CE_PIXEL  = ce_pix;
assign VGA_DE = ~(hblank | vblank);
assign VGA_HS = hs;
assign VGA_VS = vs;
assign VGA_R  = r;
assign VGA_G  = g;
assign VGA_B  = b;

assign AUDIO_S   = 1;
assign AUDIO_L   = audio_l;
assign AUDIO_R   = audio_r;
assign AUDIO_MIX = 0;

// slow blink: boot failed or the CPU halted (no SYN)
reg [24:0] blink;
always @(posedge clk_sys) blink <= blink + 1'd1;
assign LED_USER = (boot_error | halted) & blink[23];

endmodule
