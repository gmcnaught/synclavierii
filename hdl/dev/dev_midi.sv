// D70-D73 MIDI subsystem card, one card at subsystem 16
// (docs/devices/d70-midi-subsystem.md section 9; sim/devices/midi.py):
//
//   D70 SYSSEL  write: subsystem select; read: the select if 16, else 0
//   D71 MCHA    write: port (bits 0-2: 0-3 out, 4 in) and reset (bit 3)
//       MSTA    read: bit 0 = input FIFO not empty (select 16), else 0
//   D72 MDAT    read, port 4: next input byte (0 if empty); write, ports
//               0-3: an output byte. With the reset bit set an MDAT access
//               empties the input FIFO (port 4); reads 0, writes dropped.
//   D73         reads 0, writes ignored.
//
// Input: 64-byte FIFO from rx_valid/rx_data (a byte arriving with it full
// is dropped). Output: the four ports share one 256-byte FIFO drained by
// tx_valid/tx_ready (SYN-5.3's All Notes Off sends 48 bytes per port with
// no status checks); a byte written with it full is dropped.
// Accesses are answered in the same clock (ack = sel), like dev_vpk.sv.
module dev_midi (
    input  logic        clk,
    input  logic        rst,

    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D70, 1 D71, 2 D72, 3 D73
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,

    input  logic        rx_valid,     // a byte from the MIDI in jack
    input  logic [7:0]  rx_data,

    output logic        tx_valid,     // a byte for the MIDI out jack
    output logic [7:0]  tx_data,
    input  logic        tx_ready
);
    localparam logic [15:0] SUBSYS = 16'd16;

    logic [15:0] ssel;
    logic [3:0]  mcha;
    wire         here = ssel == SUBSYS;

    // ------------------------------------------------------------ input FIFO
    logic [7:0] in_mem [64];
    logic [5:0] in_rp, in_wp;
    logic [6:0] in_n;

    // --------------------------------------------------------- output FIFO
    logic [7:0] out_mem [256];
    logic [7:0] out_rp, out_wp, out_q;
    logic [8:0] out_n;
    logic       out_q_ok;                 // out_q holds out_mem[out_rp]

    // ------------------------------------------------------------ registers
    wire acc     = sel && (rd || wr);
    wire mdat    = acc && reg_sel == 2'd2 && here;
    wire in_port = mcha[2:0] == 3'd4;
    wire flush   = mdat && mcha[3] && in_port;
    wire pop     = mdat && rd && !mcha[3] && in_port && in_n != 7'd0;
    wire push_o  = mdat && wr && !mcha[3] && !mcha[2] && out_n != 9'd256;
    wire push_i  = rx_valid && in_n != 7'd64;

    always_comb begin
        rdata = 16'd0;
        if (here)
            case (reg_sel)
                2'd0: rdata = ssel;
                2'd1: rdata = {15'd0, in_n != 7'd0};
                2'd2: rdata = pop ? {8'd0, in_mem[in_rp]} : 16'd0;
                default: rdata = 16'd0;
            endcase
    end
    assign ack = sel;

    always_ff @(posedge clk) begin
        if (rst) begin
            ssel <= '0; mcha <= '0;
            in_rp <= '0; in_wp <= '0; in_n <= '0;
        end else begin
            if (acc && wr && reg_sel == 2'd0) ssel <= wdata;
            if (acc && wr && reg_sel == 2'd1) mcha <= wdata[3:0];
            if (flush) begin
                in_rp <= '0; in_wp <= '0; in_n <= '0;
            end else begin
                if (push_i) begin in_mem[in_wp] <= rx_data; in_wp <= in_wp + 6'd1; end
                if (pop) in_rp <= in_rp + 6'd1;
                in_n <= in_n + {6'd0, push_i} - {6'd0, pop};
            end
        end
    end

    // output: block RAM with a one-clock read into out_q
    wire send = tx_valid && tx_ready;
    always_ff @(posedge clk) begin
        if (push_o) out_mem[out_wp] <= wdata[7:0];
        out_q <= out_mem[send ? out_rp + 8'd1 : out_rp];
    end
    always_ff @(posedge clk) begin
        if (rst) begin
            out_rp <= '0; out_wp <= '0; out_n <= '0; out_q_ok <= 1'b0;
        end else begin
            if (push_o) out_wp <= out_wp + 8'd1;
            if (send) out_rp <= out_rp + 8'd1;
            out_n <= out_n + {8'd0, push_o} - {8'd0, send};
            // out_q holds the head next clock if the head was written before
            // this clock (an entry written this clock is read the clock after)
            out_q_ok <= out_n - {8'd0, send} != 9'd0;
        end
    end
    assign tx_valid = out_q_ok && out_n != 9'd0;
    assign tx_data  = out_q;
endmodule

// MIDI out: 8N1 at BAUD (or ALT_BAUD when alt), one byte from a valid/ready
// source at a time.
module midi_uart_tx #(
    parameter longint CLK_HZ = 50_000_000,
    parameter longint BAUD = 31_250,
    parameter longint ALT_BAUD = 9_600
) (
    input  logic       clk,
    input  logic       rst,
    input  logic       alt,
    input  logic       valid,
    input  logic [7:0] data,
    output logic       ready,
    output logic       txd
);
    localparam int DIV = int'(CLK_HZ / BAUD);
    localparam int ALT_DIV = int'(CLK_HZ / ALT_BAUD);
    logic [15:0] cnt;
    logic [3:0]  bitn;                    // 0 idle, 1 start, 2-9 data, 10 stop
    logic [7:0]  sh;
    assign ready = bitn == 4'd0;
    always_ff @(posedge clk) begin
        if (rst) begin
            bitn <= '0; txd <= 1'b1; cnt <= '0;
        end else if (bitn == 4'd0) begin
            txd <= 1'b1;
            if (valid) begin
                sh <= data; bitn <= 4'd1; txd <= 1'b0;
                cnt <= 16'(alt ? ALT_DIV - 1 : DIV - 1);
            end
        end else if (cnt != 16'd0) begin
            cnt <= cnt - 16'd1;
        end else begin
            cnt <= 16'(alt ? ALT_DIV - 1 : DIV - 1);
            if (bitn == 4'd10) begin
                bitn <= 4'd0; txd <= 1'b1;
            end else if (bitn == 4'd9) begin
                bitn <= 4'd10; txd <= 1'b1;      // stop bit
            end else begin
                txd <= sh[0]; sh <= {1'b0, sh[7:1]}; bitn <= bitn + 4'd1;
            end
        end
    end
endmodule
