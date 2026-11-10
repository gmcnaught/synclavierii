// D32/D33 multichannel distributor, 8 or 16 outputs (M19): the model of
// sim/devices/multi.py, documented in docs/devices/d32-multichannel.md.
//
//   D32 write: subsystem select (0o20 presence port, 0o21 routing port);
//       read: 0.
//   D33 write (0o21 selected): bits 7-0 input, 13-8 output, 14 on. The
//       input is switched to that output, or off. The voice side wired to
//       the input (the decode below) gets the tag {connected, output[3:0]}
//       (connected = on and output < outputs) on rt_*: dev_fm and dev_poly
//       keep a tag per voice side and mix the selected output pair with it.
//       A D33 write waits while the FM engine is busy with a sample instant
//       already passed, as D160-D163 accesses do, so that sample is mixed
//       with the routing it had (the simulator mixes it before the write).
//   D33 read: 0o20 selected: 1; 0o21 selected: bit 0 = the last written
//       input is connected and its voice side sounds (q_* asks dev_fm or
//       dev_poly: fm_live, poly_live); else 0.
// Inputs m = 4k + r: k 0-15 FM voice 4 (k >> 1) + ((r + 3) & 3), side k & 1;
// k 16-63 poly voice 4 ((k - 16) >> 1) + r (32 x bin + channel), side
// (k - 16) & 1 (0 left, 1 right).
// Outputs: 16 unless the state image says 8 (device 3 index 16). No load
// port otherwise: the distributor starts as at power-on.
module dev_multi (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic        reg_sel,      // 0 D32, 1 D33
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    input  logic        fm_busy,

    input  logic        ld_we,        // state load: device 3 (sim/lockstep.py _device_header)
    input  logic [12:0] ld_addr,
    input  logic [31:0] ld_data,

    output logic        rt_we,        // a routing write for this voice side
    output logic        rt_fm,        // 1 FM voice, 0 poly voice
    output logic [6:0]  rt_voice,
    output logic        rt_side,
    output logic [4:0]  rt_tag,       // {connected, output[3:0]}

    output logic        q_fm,         // the detector's question: the last input's voice side
    output logic [6:0]  q_voice,
    output logic        q_side,
    input  logic        fm_live,
    input  logic        poly_live
);
    localparam logic [7:0] SEL_PRESENT = 8'o20, SEL_PORT = 8'o21;

    logic [7:0] select, last;
    logic       last_conn, outs16, rst_d;

    // input -> voice side
    function automatic logic [8:0] decode(input logic [7:0] m);   // {fm, voice[6:0], side}
        logic [5:0] k, kk;
        logic [1:0] r;
        k = m[7:2]; r = m[1:0];
        kk = k - 6'd16;
        if (k < 6'd16) decode = {1'b1, 2'b00, k[3:1], 2'(r + 2'd3), k[0]};
        else           decode = {1'b0, kk[5:1], r, kk[0]};
    endfunction

    wire [8:0] qd = decode(last);
    assign q_fm = qd[8];
    assign q_voice = qd[7:1];
    assign q_side = qd[0];

    wire       d33 = reg_sel;
    assign ack = sel && !(wr && d33 && fm_busy);
    always_comb begin
        rdata = 16'd0;
        if (d33 && select == SEL_PRESENT) rdata = 16'd1;
        else if (d33 && select == SEL_PORT) rdata = {15'd0, last_conn && (q_fm ? fm_live : poly_live)};
    end

    wire [5:0] w_out  = wdata[13:8];
    wire       w_conn = wdata[14] && w_out < (outs16 ? 6'd16 : 6'd8);
    wire [8:0] wd     = decode(wdata[7:0]);

    always_ff @(posedge clk) begin
        rst_d <= rst;
        rt_we <= 1'b0;
        if (rst) begin
            select <= '0; last <= '0; last_conn <= 1'b0;
            if (!rst_d) outs16 <= 1'b1;
            else if (ld_we && ld_addr == 13'd16) outs16 <= ld_data[4:0] != 5'd8;
        end else if (ack && wr) begin
            if (!d33) select <= wdata[7:0];
            else if (select == SEL_PORT) begin
                last <= wdata[7:0];
                last_conn <= w_conn;
                rt_we <= 1'b1;
                rt_fm <= wd[8]; rt_voice <= wd[7:1]; rt_side <= wd[0];
                rt_tag <= {w_conn, w_out[3:0]};
            end
        end
    end
endmodule
