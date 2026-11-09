// D130/D131 original keyboard, button panel and display (sim/devices/synth.py
// OriginalKeyboard).
//   CREG (D131 write) = 100 + I: D130 reads clavier octave I (12 key bits,
//     0 = down; octave 5 has one key); 110 + I: D130 reads panel I (16
//     buttons, 1 = pressed). Other D130/D131 reads: no SYN when `strict`,
//     else 0 (the RTP runs non-strict, as sim.rtp).
//   D130 write: data register; with CREG = 10 + I (no read bit, no 20) it
//     sets panel I's lights. CREG = 40 + I (I 0-2, no other bits) after a
//     CREG without 40 latches the data register into display word I
//     (LOAD.ORK.DISPLAY's EXW pulse). CREG = 260 (start the A/D conversion
//     and external write, also bit 40) latches nothing: SYN-5.3 writes it
//     right after the display and the old rule blanked word 0 ("Err4" -> "Er").
// Key and button state come from the host side.
module dev_keyboard (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic        reg_sel,      // 0 D130, 1 D131
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        nosyn,
    input  logic        strict,

    input  logic        host_we,      // set clavier octave / panel word
    input  logic        host_panel,   // 0: clavier octave (0-5), 1: panel (0-7)
    input  logic [2:0]  host_index,
    input  logic [15:0] host_value,
    output logic [15:0] lights [8],
    output logic [15:0] display [3],

    input  logic        ld_we,        // state load (simulation): 0 creg, 1 dreg,
    input  logic [4:0]  ld_addr,      // 2-7 clavier, 8-15 buttons, 16-23 lights,
    input  logic [31:0] ld_data       // 24-26 display
);
    localparam logic [15:0] READ_BIT = 16'o100, PANEL_BIT = 16'o10, STROBE_BIT = 16'o40;
    logic [15:0] creg, dreg;
    logic [15:0] clavier [6];
    logic [15:0] buttons [8];

    wire [2:0] i = creg[2:0];
    wire known = !reg_sel && (creg & READ_BIT) != 0 && ((creg & PANEL_BIT) != 0 || i < 3'd6);
    assign rdata = !known ? 16'd0 : (creg & PANEL_BIT) != 0 ? buttons[i] : clavier[i];
    assign nosyn = sel && rd && !known && strict;
    assign ack   = sel && !nosyn;

    always_ff @(posedge clk) begin
        if (rst) begin
            if (ld_we) begin
                if (ld_addr == 5'd0) creg <= ld_data[15:0];
                else if (ld_addr == 5'd1) dreg <= ld_data[15:0];
                else if (ld_addr < 5'd8) clavier[ld_addr[2:0] - 3'd2] <= ld_data[15:0];
                else if (ld_addr < 5'd16) buttons[ld_addr[2:0]] <= ld_data[15:0];
                else if (ld_addr < 5'd24) lights[ld_addr[2:0]] <= ld_data[15:0];
                else if (ld_addr < 5'd27) display[ld_addr[1:0]] <= ld_data[15:0];
            end
        end else begin
            if (host_we) begin
                if (host_panel) buttons[host_index] <= host_value;
                else clavier[host_index] <= host_value;
            end
            if (ack && wr) begin
                if (reg_sel) begin
                    creg <= wdata;
                    if ((wdata & 16'o177770) == STROBE_BIT && (creg & STROBE_BIT) == 0
                            && wdata[2:0] < 3'd3)
                        display[wdata[1:0]] <= dreg;
                end else begin
                    dreg <= wdata;
                    if ((creg & PANEL_BIT) != 0 && (creg & (READ_BIT | 16'o20)) == 0)
                        lights[i] <= wdata;
                end
            end
        end
    end
endmodule
