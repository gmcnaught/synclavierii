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
    input  logic [13:0] hw_cfg,          // OSD Hardware page (LOCKSTEP_HWCFG)

    input  logic [10:0] ps2_key,
    input  logic [24:0] ps2_mouse,
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
    output logic [5:0]  sd_blk_cnt3,
    output logic [5:0]  sd_blk_cnt4,
    input  logic [4:0]  sd_ack,
    input  logic [13:0] sd_buff_addr,
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
    output logic        poly_clearing,
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
    input  logic        vpk_host_we,
    input  logic [2:0]  vpk_host_op,
    input  logic [7:0]  vpk_host_addr,
    input  logic [7:0]  vpk_host_data,
    input  logic        mouse_host_we,
    input  logic [2:0]  mouse_host_buttons,
    input  logic [15:0] mouse_host_dxy,
    input  logic        midi_card_we,
    input  logic [7:0]  midi_card_byte,
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
    logic [26:0] xr_addr;
    logic        xr_rd, xr_wr, xr_wide, xr_ack;
    logic [15:0] xr_wdata, xr_rdata;
    logic [26:0] xs_addr;
    logic        xs_rd, xs_ack, xs_rvalid;
    logic [15:0] xs_rdata;

    assign dev_rd = 1'b0;
    assign dev_wr = 1'b0;
    assign dev_num = 7'd0;
    assign dev_wdata = 16'd0;

    // one clock in simulation: the video runs at clk / 2
    synclavier_core core (
        .clk, .rst_hard, .rst, .rt_enable, .rt_voices(rt_enable), .clk_vid(clk), .ps2_key, .ps2_mouse, .color(2'd0), .panel_over(1'b0), .stall_view(1'b0), .hw_cfg,
        .img_mounted, .img_readonly, .img_size, .sd_lba0, .sd_lba1, .sd_lba2, .sd_lba3, .sd_lba4, .sd_rd, .sd_wr, .sd_blk_cnt3, .sd_blk_cnt4, .sd_ack,
        .sd_buff_addr, .sd_buff_dout, .sd_buff_din, .sd_buff_wr,
        .xr_addr, .xr_rd, .xr_wr, .xr_wide, .xr_wdata, .xr_rdata, .xr_ack,
        .xs_addr, .xs_rd, .xs_ack, .xs_rvalid, .xs_rdata,
        .ce_pix, .vga_r, .vga_g, .vga_b, .vga_hs, .vga_vs, .vga_hblank, .vga_vblank,
        .audio_l(), .audio_r(),
        .midi_rxd(1'b1), .midi_txd(), .mouse_host_we, .mouse_host_buttons, .mouse_host_dxy, .midi_card_we, .midi_card_byte, .kb_host_we, .kb_host_panel, .kb_host_index, .kb_host_value,
        .vpk_host_we, .vpk_host_op, .vpk_host_addr, .vpk_host_data,
        .led_disk, .booting, .boot_error, .halted, .poly_clearing,
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
        .s_addr(xs_addr), .s_rd(xs_rd), .s_ack(xs_ack), .s_rvalid(xs_rvalid), .s_rdata(xs_rdata),
        .DDRAM_BUSY, .DDRAM_BURSTCNT, .DDRAM_ADDR, .DDRAM_DOUT, .DDRAM_DOUT_READY, .DDRAM_RD,
        .DDRAM_DIN, .DDRAM_BE, .DDRAM_WE
    );
endmodule
