// CRT Adjust: picture position and width on a CRT, for the core's
// 640 x 480 60 Hz video (term_display: 800 x 525 clocks a frame, HSync
// 656-751, VSync lines 490-491, active-high pulses).
//
//   enable = 0 : exact combinational passthrough.
//   enable = 1 : the outputs are regenerated from counters locked to the
//                input's blanking, one line and two pixels later than the
//                input (the line buffer below), so every output keeps its
//                relation to the others.
//   hpos       : signed steps of 4 pixels; + moves the picture right (HSync
//                earlier). Only the sync pulse moves: blanking and DE stay,
//                so the MiSTer scaler (which frames the picture by DE) shows
//                the same HDMI picture.
//   vpos       : signed lines; + moves the picture down (VSync earlier).
//   hsize      : signed, -12..+10; each line is resampled about its centre
//                with a pixel period of (32 + hsize) / 32 input pixels:
//                + wider (edges cut), - narrower (black borders). Nearest
//                pixel, the same pattern every line. Unlike hpos/vpos this
//                changes the picture itself, so HDMI shows it too.
//
// The resampled line N is read while line N + 1 is written (two banks of
// 1024 pixels). Output pixel c shows input pixel
// floor((320 * hsize + 32 * c) / (32 + hsize)): pixel 320 stays put.
module crt_adjust #(
    parameter int H_ACT = 640, HS_START = 656, HS_W = 96,
    parameter int V_ACT = 480, V_TOT = 525, VS_START = 490, VS_W = 2
) (
    input  logic              clk,
    input  logic              ce,
    input  logic              enable,
    input  logic signed [4:0] hsize,
    input  logic signed [3:0] hpos,
    input  logic signed [3:0] vpos,
    input  logic [7:0]        r_in, g_in, b_in,
    input  logic              hs_in, vs_in, hblank_in, vblank_in,
    output logic [7:0]        r_out, g_out, b_out,
    output logic              hs_out, vs_out, hblank_out, vblank_out
);
    // ------------------------------------------------ input position (x, y)
    logic        hb_d = 1'b1, vb_d = 1'b1;
    logic [10:0] xr = '0;
    logic [9:0]  yr = '0;
    wire         ls = hb_d && !hblank_in;                  // first active pixel of a line
    wire  [10:0] xc = ls ? 11'd0 : xr;
    wire  [9:0]  yc = !ls ? yr : (vb_d && !vblank_in) ? 10'd0 : yr + 10'd1;
    // output line: one line behind the input
    wire  [9:0]  yo = yc == 10'd0 ? 10'(V_TOT - 1) : yc - 10'd1;

    // ------------------------------------------------------- line buffer
    logic [23:0] mem [0:2047];
    logic        wb = 1'b0;
    wire         wbc = ls ? !wb : wb;                      // bank written this line
    always_ff @(posedge clk) if (ce) begin
        hb_d <= hblank_in;
        vb_d <= vblank_in;
        xr <= xc + 11'd1;
        yr <= yc;
        wb <= wbc;
        if (!hblank_in && xc < 11'd1024) mem[{wbc, xc[9:0]}] <= {r_in, g_in, b_in};
    end

    // ------------------- start of a line in input pixels: p0 = floor(320 k / a)
    // Divided by repeated subtraction while the output is in vertical
    // blanking (at most 192 steps); a is latched with it, once a frame.
    logic        [5:0]  a = 6'd32;
    logic signed [13:0] n = '0;
    logic signed [11:0] q = '0;
    logic signed [11:0] p0 = '0;
    logic        [5:0]  r0 = '0;
    logic               div_busy = 1'b0;
    wire signed  [13:0] a14 = {8'd0, a};
    always_ff @(posedge clk) begin
        if (ce && ls && yo == 10'(V_ACT + 1)) begin
            a <= 6'(7'sd32 + hsize);
            n <= (14'(hsize) <<< 8) + (14'(hsize) <<< 6);   // 320 k
            q <= '0;
            div_busy <= 1'b1;
        end else if (div_busy) begin
            if (n < 0) begin n <= n + a14; q <= q - 12'sd1; end
            else if (n >= a14) begin n <= n - a14; q <= q + 12'sd1; end
            else begin p0 <= q; r0 <= n[5:0]; div_busy <= 1'b0; end
        end
    end

    // ---------------------------------------- read side: source pixel of xc
    logic signed [11:0] pr = '0;
    logic        [6:0]  remr = '0;
    wire signed  [11:0] pc = ls ? p0 : pr;
    wire         [6:0]  remc = ls ? {1'b0, r0} : remr;
    wire         [6:0]  rs = remc + 7'd32;
    logic [10:0] raddr;
    logic        rval1 = 1'b0, rval2 = 1'b0;
    logic [23:0] qd;
    always_ff @(posedge clk) if (ce) begin
        if (rs >= {a, 1'b0}) begin pr <= pc + 12'sd2; remr <= rs - {a, 1'b0}; end
        else if (rs >= {1'b0, a}) begin pr <= pc + 12'sd1; remr <= rs - {1'b0, a}; end
        else begin pr <= pc; remr <= rs; end
        raddr <= {!wbc, pc[9:0]};
        rval1 <= xc < 11'(H_ACT) && yo < 10'(V_ACT) && pc >= 0 && pc < 12'(H_ACT);
        qd <= mem[raddr];
        rval2 <= rval1;
    end

    // ------------------------------------------------- regenerated timing
    wire signed [11:0] hs0 = 12'(HS_START) - (12'(hpos) <<< 2);
    wire signed [11:0] vs0 = 12'(VS_START) - 12'(vpos);
    wire        hs_c = $signed({1'b0, xc}) >= hs0 && $signed({1'b0, xc}) < hs0 + 12'(HS_W);
    wire        vs_c = $signed({2'b0, yo}) >= vs0 && $signed({2'b0, yo}) < vs0 + 12'(VS_W);
    logic [3:0] t1, t2;                                   // {hs, vs, hblank, vblank}
    always_ff @(posedge clk) if (ce) begin
        t1 <= {hs_c, vs_c, xc >= 11'(H_ACT), yo >= 10'(V_ACT)};
        t2 <= t1;
    end

    wire [23:0] rgb = rval2 ? qd : 24'd0;
    assign {r_out, g_out, b_out} = enable ? rgb : {r_in, g_in, b_in};
    assign {hs_out, vs_out, hblank_out, vblank_out} =
        enable ? t2 : {hs_in, vs_in, hblank_in, vblank_in};
endmodule
