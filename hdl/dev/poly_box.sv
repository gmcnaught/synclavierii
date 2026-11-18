// Poly output to the 768 kHz instants (M26, docs/poly-output.md), bit for
// bit as sim/pcm.py PolyBox and PcmOut.push:
//
//   dev_poly's P(m) holds for [m x 9900, (m + 1) x 9900) ns. For each FM
//   sample (dev_fm, instant t_k), over [t_prev, t_k), d = t_k - t_prev:
//     a boundary b = m x 9900 with b < t_k (the next one not yet used):
//       y = P_cur x (b - t_prev) + P(m) x (t_k - b);  P_cur = P(m)
//     else y = P_cur x d
//     x_poly = y x RECIP(d) >>> 20     (RECIP: 1302 -> 51543, 1303 -> 51503, else 0)
//     x' = sat27((fm >>> 14) + x_poly)                to pcm_out
//   After reset t_prev = 0, the next boundary is tick 0, P_cur = 0.
//
// Instant times: `now` counts voice time as dev_poly's does; dev_fm says
// when an instant falls in a tick (`inst`, `inst_d` ns into it), and its
// sample for it comes later, in order. FM samples wait here (up to 8)
// until the P they need has come; with voices on CPU time (`hold_ok`) 4
// waiting hold the CPU (`stall`), which stops voice time, so the output
// never depends on how long dev_poly takes. With voices on real time (M14)
// holding the CPU would not stop them (it would only add lag): with 8
// waiting the oldest goes out with the P it needs taken as P_cur (`late`
// counts these), and that P is dropped when it comes. Without `en` (no dev_poly) x' is the FM part alone.
//
// One sample at a time, two multipliers used in turn (8 clocks a sample;
// samples come every 65 clocks or more of real time).
module poly_box (
    input  logic        clk,
    input  logic        rst,
    input  logic        en,
    input  logic        hold_ok,       // voices on CPU time: stall stops them (not on real time)
    input  logic        tick,
    input  logic [9:0]  tick_ns,
    input  logic        inst,          // dev_fm: a sample instant in this tick ...
    input  logic [9:0]  inst_d,        // ... this many ns into it
    input  logic        fm_valid,
    input  logic signed [39:0] fm_l,
    input  logic signed [39:0] fm_r,
    input  logic        p_valid,
    input  logic signed [31:0] p_l,
    input  logic signed [31:0] p_r,
    output logic        out_valid,
    output logic signed [26:0] out_l,
    output logic signed [26:0] out_r,
    output logic        stall,
    output logic [15:0] late
);
    localparam logic [47:0] F0_NS = 48'd9900;
    localparam logic [15:0] R1302 = 16'd51543, R1303 = 16'd51503;

    logic [47:0] now;
    // instant times and FM samples, in order (the k-th time is the k-th sample's)
    logic [47:0] tq [8];
    logic [2:0]  tq_wp, tq_rp;
    logic [39:0] fl [8], fr [8];
    logic [2:0]  fq_wp, fq_rp;
    logic [3:0]  fq_n;                            // FM samples waiting
    // P values come, in order
    logic [53:0] pq [32];                         // {left, right}
    logic [4:0]  pq_wp, pq_rp;
    logic [5:0]  pq_n;
    logic [31:0] debt;                            // boundaries passed without their P (late)

    logic [47:0] t_prev, nb;                      // last instant; next boundary
    logic signed [26:0] c_l, c_r;                 // P_cur
    // the sample being worked on
    logic [3:0]  st;
    logic [47:0] t_k;
    logic [12:0] w_old, w_new;
    logic signed [26:0] o_l, o_r;                 // P_cur before the interval
    logic signed [26:0] n_l, n_r;                 // P(m) (or P_cur)
    logic [15:0] rcp;
    logic signed [39:0] f_l, f_r;
    logic signed [40:0] ma, ya;                   // P x w, a partial sum
    logic signed [40:0] y_l, y_r;
    logic signed [57:0] mb;
    logic signed [37:0] x_l;

    wire  [47:0] t_head = tq[tq_rp];
    wire  [47:0] d_w = t_head - t_prev;
    wire         bnd = en && nb < t_head;         // a boundary inside the interval
    wire         p_have = pq_n != 6'd0;
    wire  [53:0] p_head = pq[pq_rp];
    wire signed [26:0] h_l = p_head[53:27], h_r = p_head[26:0];
    wire         go = st == 4'd0 && fq_n != 4'd0 && (!bnd || p_have || fq_n == 4'd8);
    wire         p_take = go && bnd && p_have;
    wire         p_drop = p_valid && debt != 32'd0;
    assign stall = hold_ok && fq_n >= 4'd4;

    // the multipliers' operands, by step
    logic signed [26:0] a_x;
    logic [12:0] a_w;
    logic signed [40:0] b_x;
    always_comb begin
        case (st)
            4'd1: begin a_x = o_l; a_w = w_old; end
            4'd2: begin a_x = n_l; a_w = w_new; end
            4'd3: begin a_x = o_r; a_w = w_old; end
            default: begin a_x = n_r; a_w = w_new; end
        endcase
        b_x = st == 4'd4 ? y_l : y_r;
    end

    function automatic logic signed [26:0] sat27(input logic signed [38:0] v);
        if (v > 39'sd67108863) sat27 = 27'sd67108863;
        else if (v < -39'sd67108864) sat27 = -27'sd67108864;
        else sat27 = v[26:0];
    endfunction

    always_ff @(posedge clk) begin
        out_valid <= 1'b0;
        if (rst) begin
            now <= '0;
            tq_wp <= '0; tq_rp <= '0; fq_wp <= '0; fq_rp <= '0; fq_n <= '0;
            pq_wp <= '0; pq_rp <= '0; pq_n <= '0; debt <= '0; late <= '0;
            t_prev <= '0; nb <= '0; c_l <= '0; c_r <= '0; st <= '0;
        end else begin
            if (tick) now <= now + 48'(tick_ns);
            if (tick && inst) begin
                tq[tq_wp] <= now + 48'(inst_d);
                tq_wp <= tq_wp + 3'd1;
            end
            if (fm_valid) begin
                fl[fq_wp] <= fm_l; fr[fq_wp] <= fm_r;
                fq_wp <= fq_wp + 3'd1;
            end
            if (p_valid && !p_drop) begin
                pq[pq_wp] <= {p_l[26:0], p_r[26:0]};
                pq_wp <= pq_wp + 5'd1;
            end
            pq_n <= pq_n + 6'(p_valid && !p_drop) - 6'(p_take);
            if (p_take) pq_rp <= pq_rp + 5'd1;
            debt <= debt + 32'(go && bnd && !p_have) - 32'(p_drop);
            if (go && bnd && !p_have && late != 16'hFFFF) late <= late + 16'd1;
            fq_n <= fq_n + 4'(fm_valid) - 4'(st == 4'd7);

            case (st)
                4'd0: if (go) begin
                    t_k <= t_head;
                    o_l <= c_l; o_r <= c_r;
                    tq_rp <= tq_rp + 3'd1;
                    f_l <= fl[fq_rp]; f_r <= fr[fq_rp];
                    rcp <= d_w == 48'd1302 ? R1302 : d_w == 48'd1303 ? R1303 : 16'd0;
                    if (bnd) begin
                        w_old <= 13'(nb - t_prev);
                        w_new <= 13'(t_head - nb);
                        n_l <= p_have ? h_l : c_l;
                        n_r <= p_have ? h_r : c_r;
                        nb <= nb + F0_NS;
                    end else begin
                        w_old <= 13'(d_w); w_new <= 13'd0;
                        n_l <= '0; n_r <= '0;
                    end
                    st <= 4'd1;
                end
                4'd1, 4'd2, 4'd3, 4'd4: begin
                    // 1: Pc_l w_old; 2: Pn_l w_new; 3: Pc_r w_old; 4: Pn_r w_new
                    ma <= 41'(a_x * $signed({1'b0, a_w}));
                    if (st == 4'd2 || st == 4'd4) ya <= ma;
                    if (st == 4'd3) y_l <= ya + ma;
                    if (st == 4'd4) mb <= b_x * $signed({1'b0, rcp});
                    st <= st + 4'd1;
                end
                4'd5: begin
                    y_r <= ya + ma;
                    x_l <= 38'(mb >>> 20);
                    st <= 4'd6;
                end
                4'd6: begin
                    mb <= b_x * $signed({1'b0, rcp});
                    st <= 4'd7;
                end
                4'd7: begin
                    out_l <= sat27(39'(f_l >>> 14) + 39'(x_l));
                    out_r <= sat27(39'(f_r >>> 14) + 39'(38'(mb >>> 20)));
                    out_valid <= 1'b1;
                    fq_rp <= fq_rp + 3'd1;
                    t_prev <= t_k;
                    st <= 4'd0;
                end
                default: st <= 4'd0;
            endcase
            // P_cur moves on when the boundary is used
            if (go && bnd) begin
                c_l <= p_have ? h_l : c_l;
                c_r <= p_have ? h_r : c_r;
            end
        end
    end
endmodule
