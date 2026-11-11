// D40/D41 printer port of the D40Q card and bit 0 of D54, its interrupt
// (sim/devices/printer.py; docs/devices/d40-printer.md):
//   D40 write: a byte to the printer (tx_valid/tx_data); the transmitter is
//              busy one character time (10 bits at the baud rate, in
//              simulated time), then raises its transmit interrupt.
//   D40 read:  0 (no byte from the printer).
//   D41 read:  4 transmitter empty | 1 transmit interrupt (receive-ready,
//              2, never). D41 write: clears the transmit interrupt; bit 15
//              sets the baud rate from bits 10-8. Until then a byte takes
//              10 us (sim/devices/printer.py FAST_NS: SYN-5.3's hardcopy
//              needs a port that never makes it wait).
//   D54 write: interrupt enables (bit 0 = D40; the mouse keeps bit 2).
//   D54 read:  enables & {transmit interrupt} in bit 0.
//   irq (PSW bit 10) while D54 bit 0 is pending.
// The transmitter's timing is dev_terminal.sv's (a write wins over the
// tick of the same clock).
module dev_printer (
    input  logic        clk,
    input  logic        rst,
    input  logic        tick,
    input  logic [9:0]  tick_ns,

    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D40, 1 D41, 2 D54
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        irq,

    output logic        tx_valid,     // a byte printed
    output logic [7:0]  tx_data
);
    logic [2:0]  baud;
    logic        fast;                // no baud rate set yet: 10 us a byte
    logic        xmit_irq, enable;
    logic signed [31:0] tx_busy;
    logic signed [31:0] char_ns;
    always_comb
        if (fast) char_ns = 10_000;
        else case (baud)     // round(10e9 / baud)
            3'd0: char_ns = 33_333_333;
            3'd1: char_ns = 8_333_333;
            3'd2: char_ns = 4_166_667;
            3'd3: char_ns = 2_083_333;
            3'd4: char_ns = 1_041_667;
            3'd5: char_ns = 520_833;
            3'd6: char_ns = 260_417;
            default: char_ns = 130_208;
        endcase

    assign ack = sel;
    assign irq = enable && xmit_irq;
    always_comb
        case (reg_sel)
            2'd0:    rdata = 16'd0;
            2'd1:    rdata = {13'd0, tx_busy <= 0, 1'b0, xmit_irq};
            default: rdata = {15'd0, irq};
        endcase
    assign tx_valid = sel && wr && reg_sel == 2'd0;
    assign tx_data  = wdata[7:0];

    wire signed [31:0] ns = {22'd0, tick_ns};
    always_ff @(posedge clk) begin
        if (rst) begin
            baud <= 3'd4; fast <= 1'b1; xmit_irq <= 1'b0; enable <= 1'b0; tx_busy <= '0;
        end else if (sel && wr) begin
            case (reg_sel)
                2'd0: begin xmit_irq <= 1'b0; tx_busy <= char_ns; end
                2'd1: begin xmit_irq <= 1'b0; if (wdata[15]) begin baud <= wdata[10:8]; fast <= 1'b0; end end
                default: enable <= wdata[0];
            endcase
        end else if (tick && tx_busy > 0) begin
            tx_busy <= tx_busy - ns;
            if (tx_busy - ns <= 0) xmit_irq <= 1'b1;
        end
    end
endmodule
