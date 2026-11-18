// Audio output stage (M5, M23): the voice engine's 768 kHz sums to 48 kHz
// 16-bit PCM, bit for bit as sim/pcm.py:
//   x' = in >>> 14 (floor)
//   every 16th input, newest at n:
//     acc = sum(fir_coeff(j) x x'[n - j], j = 0 .. 511)   (x' = 0 before the first)
//     pcm = clip(round_half_even(acc x 32767 / 2^41))
// fir_coeff (pcm_fir.svh, tools/gen_pcm_fir.py): a 512-tap low-pass at
// 21 kHz with integer taps summing to 2^20. Gain (M23): one voice at full
// level, hard-panned, = 1/16 of full scale (was 1/4; 32 voices clipped). The filter keeps the voice
// staircase's images (256 x f and up) out of the audio band.
//
// One multiply-accumulate a clock per channel: 512 clocks a sum, of the
// 16 x 65 = 1041 a 50 MHz clock has between outputs in real time. When
// simulated time runs faster than that (lockstep without the throttle), a
// sum that falls due while one is running waits, and `stall` holds the CPU
// (as dev_fm's does) until it starts; the output does not depend on when a
// sum is computed. The history is a 1024-entry circular buffer per channel:
// inputs that arrive during a sum land in entries it does not read.
module pcm_out (
    input  logic        clk,
    input  logic        rst,
    input  logic        in_valid,
    input  logic signed [39:0] in_l,
    input  logic signed [39:0] in_r,
    output logic        out_valid,
    output logic signed [15:0] out_l,
    output logic signed [15:0] out_r,
    output logic        stall          // a sum is due while another runs: hold the CPU
);
    `include "pcm_fir.svh"
    localparam int XW = 26;                         // x' bits (|x'| < 2^22 for 32 voices)
    localparam int AW = XW + FIR_W + 9;             // sum of 512 products

    logic signed [XW-1:0] hist_l [1024];
    logic signed [XW-1:0] hist_r [1024];
    logic signed [XW-1:0] rd_l, rd_r;
    logic [9:0]  wp;                                // next history entry
    logic [3:0]  count;                             // inputs since the last sum fell due
    logic [2:0]  due;                               // sums due, not started
    logic [9:0]  nx_newest, nx_have;                // the next sum: newest entry, inputs in its window

    logic        busy;                              // issuing a sum's taps
    logic [9:0]  j, newest, have;

    // pipeline: S0 issue (history read, coefficient) -> S1 operands -> S2 products -> S3 sum -> S4 PCM
    logic        s1_ok, s2_ok, s3_ok, fin;
    logic        s1_first, s2_first, s3_first, s1_last, s2_last, s3_last, s1_zero;
    logic signed [FIR_W-1:0] s1_c, s2_c;
    logic signed [XW-1:0] s2_xl, s2_xr;
    logic signed [XW+FIR_W-1:0] s3_pl, s3_pr;
    logic signed [AW-1:0] acc_l, acc_r;

    // (no parameter-sized casts: Quartus 17 rejects them; signed assignments extend)
    localparam logic signed [AW+15:0] PMAX = 32767;
    localparam logic signed [AW+15:0] PMIN = -32768;
    function automatic logic signed [15:0] pcm(input logic signed [AW-1:0] a);
        logic signed [AW+15:0] ae, p, q;
        logic [40:0] r;
        ae = a;
        p = (ae <<< 15) - ae;                       // a x 32767
        q = p >>> 41;                               // floor
        r = p[40:0];
        if (r > 41'h100_0000_0000 || (r == 41'h100_0000_0000 && q[0])) q = q + 1'b1;
        if (q > PMAX) pcm = 16'sd32767;
        else if (q < PMIN) pcm = -16'sd32768;
        else pcm = q[15:0];
    endfunction

    wire fall_due = in_valid && count == 4'd15;
    wire start = !busy && due != 3'd0;

    always_ff @(posedge clk) begin
        rd_l <= hist_l[newest - j];
        rd_r <= hist_r[newest - j];
        if (in_valid && !rst) begin
            hist_l[wp] <= in_l[XW+13:14];
            hist_r[wp] <= in_r[XW+13:14];
        end
    end

    always_ff @(posedge clk) begin
        out_valid <= 1'b0;
        if (rst) begin
            wp <= '0; count <= '0; due <= '0; busy <= 1'b0;
            nx_newest <= 10'd15; nx_have <= 10'd16;
            s1_ok <= 1'b0; s2_ok <= 1'b0; s3_ok <= 1'b0; fin <= 1'b0;
        end else begin
            if (in_valid) begin
                wp <= wp + 1'b1;
                count <= count + 1'b1;
            end
            due <= due + {2'd0, fall_due} - {2'd0, start};
            if (start) begin
                busy <= 1'b1;
                j <= '0;
                newest <= nx_newest;
                have <= nx_have;
                nx_newest <= nx_newest + 10'd16;
                nx_have <= nx_have >= 10'd496 ? 10'd512 : nx_have + 10'd16;
            end else if (busy) begin
                j <= j + 1'b1;
                if (j == 10'd511) busy <= 1'b0;
            end
            // S0 -> S1
            s1_ok <= busy;
            s1_first <= busy && j == 10'd0;
            s1_last <= busy && j == 10'd511;
            s1_zero <= j >= have;
            s1_c <= fir_coeff(j[8:0]);
            // S1 -> S2
            s2_ok <= s1_ok; s2_first <= s1_first; s2_last <= s1_last;
            s2_c <= s1_c;
            s2_xl <= s1_zero ? '0 : rd_l;
            s2_xr <= s1_zero ? '0 : rd_r;
            // S2 -> S3
            s3_ok <= s2_ok; s3_first <= s2_first; s3_last <= s2_last;
            s3_pl <= s2_xl * s2_c;                  // signed, extended to the product width
            s3_pr <= s2_xr * s2_c;
            // S3: sum
            if (s3_ok && s3_first) begin
                acc_l <= s3_pl;
                acc_r <= s3_pr;
            end else if (s3_ok) begin
                acc_l <= acc_l + s3_pl;
                acc_r <= acc_r + s3_pr;
            end
            fin <= s3_ok && s3_last;
            // S4: PCM
            if (fin) begin
                out_valid <= 1'b1;
                out_l <= pcm(acc_l);
                out_r <= pcm(acc_r);
            end
        end
    end

    assign stall = busy && due != 3'd0;
endmodule
