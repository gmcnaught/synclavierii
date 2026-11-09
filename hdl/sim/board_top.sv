// Simulation top for the board-level check (hdl/sim/lockstep.cpp, BOARD):
// synclavier_core and the DDR3 bridge as on MiSTer. The bench plays the
// HPS (SD block transfers, image mounts) and the DDR3 controller, starts
// from power-on (no state is loaded), lets the boot loader boot MONITOR and
// then compares the run with a trace of sim/boot.py's boot. The port names
// the shared bench loop uses are those of able_sys_top; dev_* are dummies
// (the core answers unknown devices itself).
module board_top (
    input  logic        clk,
    input  logic        rst_hard,
    input  logic        rst,
    input  logic        rt_enable,

    input  logic [10:0] ps2_key,
    input  logic [24:0] ps2_mouse,
    input  logic [3:0]  img_mounted,
    input  logic        img_readonly,
    input  logic [63:0] img_size,
    output logic [31:0] sd_lba0,
    output logic [31:0] sd_lba1,
    output logic [31:0] sd_lba2,
    output logic [31:0] sd_lba3,
    output logic [3:0]  sd_rd,
    output logic [3:0]  sd_wr,
    input  logic [3:0]  sd_ack,
    input  logic [8:0]  sd_buff_addr,
    input  logic [7:0]  sd_buff_dout,
    output logic [7:0]  sd_buff_din,
    input  logic        sd_buff_wr,

    input  logic        DDRAM_BUSY,
    output logic [7:0]  DDRAM_BURSTCNT,
    output logic [28:0] DDRAM_ADDR,
    input  logic [63:0] DDRAM_DOUT,
    input  logic        DDRAM_DOUT_READY,
    output logic        DDRAM_RD,
    output logic [63:0] DDRAM_DIN,
    output logic [7:0]  DDRAM_BE,
    output logic        DDRAM_WE,

    output logic        ce_pix,
    output logic [7:0]  vga_r,
    output logic [7:0]  vga_g,
    output logic [7:0]  vga_b,
    output logic        vga_hs,
    output logic        vga_vs,
    output logic        vga_hblank,
    output logic        vga_vblank,
    input  logic [11:0] peek_addr,
    output logic [7:0]  peek_data,
    output logic [4:0]  top_row,
    output logic        booting,
    output logic        boot_error,
    output logic        halted,
    output logic        led_disk,

    // the shared bench loop
    output logic        dev_rd,
    output logic        dev_wr,
    output logic [6:0]  dev_num,
    output logic [15:0] dev_wdata,
    input  logic [15:0] dev_rdata,
    input  logic        dev_ack,
    input  logic        dev_nosyn,
    input  logic        dev_hold,
    input  logic [15:4] dev_irq,
    input  logic        halt_req,
    input  logic        kb_host_we,
    input  logic        kb_host_panel,
    input  logic [2:0]  kb_host_index,
    input  logic [15:0] kb_host_value,
    input  logic        term_rx_valid,
    input  logic [7:0]  term_rx_data,
    output logic        term_tx_valid,
    output logic [7:0]  term_tx_data,
    output logic        audio_valid,
    output logic signed [39:0] audio_l,
    output logic signed [39:0] audio_r,
    output logic        pcm_valid,
    output logic signed [15:0] pcm_l,
    output logic signed [15:0] pcm_r,
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
    output logic [1:0]  halt_reason
);
    logic [25:0] xr_addr;
    logic        xr_rd, xr_wr, xr_wide, xr_ack;
    logic [15:0] xr_wdata, xr_rdata;

    assign dev_rd = 1'b0;
    assign dev_wr = 1'b0;
    assign dev_num = 7'd0;
    assign dev_wdata = 16'd0;

    // one clock in simulation: the video runs at clk / 2
    synclavier_core core (
        .clk, .rst_hard, .rst, .rt_enable, .clk_vid(clk), .ps2_key, .ps2_mouse, .color(2'd0),
        .img_mounted, .img_readonly, .img_size, .sd_lba0, .sd_lba1, .sd_lba2, .sd_lba3, .sd_rd, .sd_wr, .sd_ack,
        .sd_buff_addr, .sd_buff_dout, .sd_buff_din, .sd_buff_wr,
        .xr_addr, .xr_rd, .xr_wr, .xr_wide, .xr_wdata, .xr_rdata, .xr_ack,
        .ce_pix, .vga_r, .vga_g, .vga_b, .vga_hs, .vga_vs, .vga_hblank, .vga_vblank,
        .audio_l(), .audio_r(),
        .midi_rxd(1'b1), .kb_host_we, .kb_host_panel, .kb_host_index, .kb_host_value,
        .led_disk, .booting, .boot_error, .halted,
        .sim_rx_valid(term_rx_valid), .sim_rx_data(term_rx_data), .term_tx_valid, .term_tx_data,
        .peek_addr, .peek_data, .top_row,
        .instr_done, .instr_pc, .instr_word, .regs_flat, .flags, .irq_sample, .irq_psw,
        .irq_all, .io_held, .tick, .tick_ns, .mon_valid, .mon_wr, .mon_dev, .mon_data,
        .halt_reason, .pcm_valid, .pcm_l, .pcm_r, .audio_valid,
        .audio_sum_l(audio_l), .audio_sum_r(audio_r)
    );

    ddram_word ext_memory (
        .clk, .rst(rst_hard),
        .addr(xr_addr), .rd(xr_rd), .wr(xr_wr), .wide(xr_wide), .wdata(xr_wdata), .rdata(xr_rdata), .ack(xr_ack),
        .DDRAM_BUSY, .DDRAM_BURSTCNT, .DDRAM_ADDR, .DDRAM_DOUT, .DDRAM_DOUT_READY, .DDRAM_RD,
        .DDRAM_DIN, .DDRAM_BE, .DDRAM_WE
    );
endmodule
