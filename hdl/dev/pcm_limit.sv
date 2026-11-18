// Output limiter (#76): pcm_out's unclipped 48 kHz samples to 16-bit PCM,
// bit for bit as sim/pcm.py Limiter. One gain for both sides, G / 2^24,
// 0 < G <= 2^24. Per sample (vl, vr):
//   p = max(|vl|, |vr|)
//   if p x G > T x 2^24:  G = floor(T x 2^24 / p); hold = HOLD    (attack, instant)
//   out = (v x G + 2^23) >>> 24           (|out| <= T: never clips)
//   then: hold > 0: hold -= 1;  else G = min(2^24, G + ((2^24 - G) >> REL) + 1)
// T = 29204 (-1 dBFS), HOLD = 960 (20 ms), REL = 12 (85 ms time constant).
// Off (`on` = 0): out = clip16(v), and G, hold are reset.
//
// Sequential, one multiplier: 2 + 39 (divide, on attack only) + 3 clocks a
// sample; pcm_out gives one at most every 512 clocks.
module pcm_limit (
    input  logic        clk,
    input  logic        rst,
    input  logic        on,
    input  logic        in_valid,
    input  logic signed [21:0] in_l,         // pcm_out: |v| < 2^21
    input  logic signed [21:0] in_r,
    output logic        out_valid,
    output logic signed [15:0] out_l,
    output logic signed [15:0] out_r
);
    localparam logic [24:0] ONE = 25'd16777216;
    localparam logic [38:0] TT = 39'd29204 << 24;
    localparam logic [9:0]  HOLD = 10'd960;
    localparam int          REL = 12;

    logic [24:0] g;
    logic [9:0]  hold;
    logic signed [21:0] vl, vr;
    logic [20:0] p;
    logic [2:0]  st;
    logic [5:0]  i;                              // divide: dividend bit
    logic [21:0] rem;
    logic [24:0] quo;
    logic signed [46:0] m;

    function automatic logic signed [15:0] clip16(input logic signed [21:0] v);
        if (v > 22'sd32767) clip16 = 16'sd32767;
        else if (v < -22'sd32768) clip16 = -16'sd32768;
        else clip16 = v[15:0];
    endfunction

    wire [20:0] al = vl < 0 ? 21'(-vl) : 21'(vl);
    wire [20:0] ar = vr < 0 ? 21'(-vr) : 21'(vr);
    wire [45:0] pg = p * g;                       // unsigned
    wire [21:0] rem2 = {rem[20:0], TT[i]};
    wire signed [46:0] mul = (st == 3'd4 ? vl : vr) * $signed({1'b0, g});

    always_ff @(posedge clk) begin
        out_valid <= 1'b0;
        if (rst) begin
            g <= ONE; hold <= '0; st <= '0;
        end else begin
            case (st)
                3'd0: if (in_valid) begin
                    if (!on) begin
                        out_l <= clip16(in_l);
                        out_r <= clip16(in_r);
                        out_valid <= 1'b1;
                        g <= ONE; hold <= '0;
                    end else begin
                        vl <= in_l; vr <= in_r;
                        st <= 3'd1;
                    end
                end
                3'd1: begin
                    p <= al > ar ? al : ar;
                    st <= 3'd2;
                end
                3'd2: begin
                    if (pg > 46'(TT)) begin              // attack: divide
                        rem <= '0; quo <= '0; i <= 6'd38;
                        st <= 3'd3;
                    end else st <= 3'd4;
                end
                3'd3: begin                             // restoring division, a bit a clock
                    if (rem2 >= {1'b0, p}) begin
                        rem <= rem2 - {1'b0, p};
                        quo <= {quo[23:0], 1'b1};
                    end else begin
                        rem <= rem2;
                        quo <= {quo[23:0], 1'b0};
                    end
                    if (i == 6'd0) st <= 3'd7;
                    i <= i - 6'd1;
                end
                3'd7: begin                             // the quotient is the new gain
                    g <= quo;
                    hold <= HOLD;
                    st <= 3'd4;
                end
                3'd4: begin
                    m <= mul;
                    st <= 3'd5;
                end
                3'd5: begin
                    out_l <= 16'((m + 47'sd8388608) >>> 24);
                    m <= mul;
                    st <= 3'd6;
                end
                3'd6: begin
                    out_r <= 16'((m + 47'sd8388608) >>> 24);
                    out_valid <= 1'b1;
                    if (hold != 10'd0) hold <= hold - 10'd1;
                    else if (g < ONE) g <= (g + ((ONE - g) >> REL) + 25'd1) > ONE ? ONE
                                           : g + ((ONE - g) >> REL) + 25'd1;
                    st <= 3'd0;
                end
                default: st <= 3'd0;
            endcase
        end
    end
endmodule
