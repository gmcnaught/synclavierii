// Audio output stage (M5): the voice engine's 192 kHz sums to 48 kHz
// 16-bit PCM, the same arithmetic as sim/voice.py render() + write_wav():
// the mean of 4 samples (render's box filter), times gain 1/4 (four voices
// at full level reach full scale), times 32767, divided by the full scale
// of one voice (2^31), rounded half to even (Python round()), clipped.
//   pcm = round(sum of 4 x 32767 / 2^35)
// In floating point every step of the Python path is exact for these
// magnitudes, so the two agree bit for bit.
module audio_out (
    input  logic        clk,
    input  logic        rst,
    input  logic        in_valid,
    input  logic signed [39:0] in_l,
    input  logic signed [39:0] in_r,
    output logic        out_valid,
    output logic signed [15:0] out_l,
    output logic signed [15:0] out_r
);
    logic signed [41:0] acc_l, acc_r;
    logic [1:0] count;

    function automatic logic signed [15:0] pcm(input logic signed [41:0] s4);
        logic signed [57:0] p;
        logic signed [57:0] q;
        logic [34:0] r;
        p = 58'(s4) * 58'sd32767;
        q = p >>> 35;                               // floor
        r = p[34:0];
        if (r > 35'h4_0000_0000 || (r == 35'h4_0000_0000 && q[0])) q = q + 58'sd1;
        if (q > 58'sd32767) pcm = 16'sd32767;
        else if (q < -58'sd32768) pcm = -16'sd32768;
        else pcm = q[15:0];
    endfunction

    wire signed [41:0] sum_l = acc_l + 42'(in_l);
    wire signed [41:0] sum_r = acc_r + 42'(in_r);

    always_ff @(posedge clk) begin
        out_valid <= 1'b0;
        if (rst) begin
            count <= 2'd0;
            acc_l <= '0;
            acc_r <= '0;
        end else if (in_valid) begin
            if (count == 2'd3) begin
                out_valid <= 1'b1;
                out_l <= pcm(sum_l);
                out_r <= pcm(sum_r);
                acc_l <= '0;
                acc_r <= '0;
            end else begin
                acc_l <= sum_l;
                acc_r <= sum_r;
            end
            count <= count + 2'd1;
        end
    end
endmodule
