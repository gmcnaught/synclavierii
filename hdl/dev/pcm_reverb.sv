// Output reverb (OSD Reverb; not on the instrument, docs/poly-output.md 9):
// pcm_out's unclipped 48 kHz samples, plus an 8-line feedback delay
// network's wet signal, to pcm_limit.sv, bit for bit as sim/pcm.py Reverb.
// Constants: pcm_reverb.svh (tools/gen_pcm_reverb.py). Per sample (vl, vr),
// type t (0 Off, 1 Room, 2 Hall, 3 Plate) and mix code m, with one delay
// memory mem[16384] of 20-bit words and a pointer p decremented each sample
// (a line written at p + B is read L samples later at p + B + L):
//   x = sat20((vl + vr) >>> 2)
//   d = mem[p + PD_BASE + pre(t)];  mem[p + PD_BASE] = x
//   all-pass k = 0..3:  wm = mem[p + ap_base + ap_len]
//       w = sat20(d + mul(wm, g));  mem[p + ap_base] = w;  d = wm - mul(w, g)
//   lines i = 0..7:  lp[i] += mul(mem[p + line_base + len(t, i)] - lp[i], damp(t))
//   h = Hadamard(lp)        (unnormalised; 1/sqrt(8) is in the gains)
//   lines i = 0..7:  mem[p + line_base] = sat20(mul(h[i], gain(t, i)) +- (d >>> 1))
//   out = sat22(vl + rmul(h[1], mix(t, m))), sat22(vr + rmul(h[2], mix(t, m)))
// mul(a, c) = a x c / 2^15 truncated toward zero; rmul rounds half up.
// Off: out = in. A change to a type other than Off (or the first sample
// after reset in one) starts a clear: that sample and the next 63 pass dry
// while 256 words a sample are zeroed, lp and p reset.
//
// Sequential, one multiplier: about 100 clocks a sample (a clear 257);
// pcm_out gives one at most every 512 clocks, so no input is ever waiting.
module pcm_reverb (
    input  logic        clk,
    input  logic        rst,
    input  logic [1:0]  kind,                   // OSD Reverb: 0 Off, 1 Room, 2 Hall, 3 Plate
    input  logic [1:0]  mix,                    // OSD Reverb mix code
    input  logic        in_valid,
    input  logic signed [21:0] in_l,            // pcm_out: |v| < 2^21
    input  logic signed [21:0] in_r,
    output logic        out_valid,
    output logic signed [21:0] out_l,           // to pcm_limit.sv
    output logic signed [21:0] out_r
);
    `include "pcm_reverb.svh"

    localparam logic [6:0] CLEAR = RV_CLEAR;

    typedef enum logic [2:0] {IDLE, CLR, PD, AP, LN, WHT, WR, OUT} st_t;
    st_t st;
    logic [2:0]  u;                             // step within a state
    logic [2:0]  k;                             // all-pass / line index

    // 32 M10K: max_depth keeps Quartus from the 4K x 2 mode (40 blocks for 16K x 20)
    (* ramstyle = "no_rw_check", max_depth = 2048 *) logic signed [19:0] mem [1 << RV_MEM_BITS];
    logic [13:0] raddr, waddr, ptr;
    logic signed [19:0] rdata, wdata;
    logic        we;

    logic [1:0]  kind_q, t, m;
    logic [6:0]  clr_left;
    logic [5:0]  chunk;
    logic [7:0]  ci;

    logic signed [21:0] vl, vr;
    logic signed [20:0] d;
    logic signed [19:0] wm;
    logic signed [19:0] lp [8];
    logic signed [22:0] h [8];
    logic signed [26:0] wl;

    logic signed [23:0] ma;
    logic signed [17:0] mc;
    logic signed [41:0] pr;

    function automatic logic signed [26:0] tq(input logic signed [41:0] p);   // p / 2^15 toward zero
        logic signed [41:0] q;
        q = p >>> 15;
        if (p[41] && p[14:0] != 15'd0) q = q + 42'sd1;
        tq = q[26:0];
    endfunction

    function automatic logic signed [26:0] rq(input logic signed [41:0] p);   // p / 2^15 half up
        logic signed [41:0] q;
        q = (p + 42'sd16384) >>> 15;
        rq = q[26:0];
    endfunction

    function automatic logic signed [19:0] sat20(input logic signed [27:0] v);
        if (v > 28'sd524287) sat20 = 20'sd524287;
        else if (v < -28'sd524287) sat20 = -20'sd524287;
        else sat20 = v[19:0];
    endfunction

    function automatic logic signed [21:0] sat22(input logic signed [27:0] v);
        if (v > 28'sd2097151) sat22 = 22'sd2097151;
        else if (v < -28'sd2097151) sat22 = -22'sd2097151;
        else sat22 = v[21:0];
    endfunction

    // the Hadamard transform of lp, in one clock (3 stages of 8 adders)
    logic signed [22:0] h1 [8], h2 [8], h3 [8];
    always_comb begin
        for (int j = 0; j < 8; j++) begin
            h1[j] = (j & 1) ? lp[j ^ 1] - lp[j] : lp[j] + lp[j ^ 1];
        end
        for (int j = 0; j < 8; j++) begin
            h2[j] = (j & 2) ? h1[j ^ 2] - h1[j] : h1[j] + h1[j ^ 2];
        end
        for (int j = 0; j < 8; j++) begin
            h3[j] = (j & 4) ? h2[j ^ 4] - h2[j] : h2[j] + h2[j ^ 4];
        end
    end

    wire signed [26:0] tqp = tq(pr);
    wire signed [26:0] rqp = rq(pr);
    wire signed [20:0] inj = d >>> 1;
    wire               newk = kind != kind_q;
    wire signed [26:0] lp_next = lp[k] + tqp;     // within 20 bits: lp moves toward the line output

    always_ff @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        rdata <= mem[raddr];
        pr <= ma * mc;
    end

    always_ff @(posedge clk) begin
        out_valid <= 1'b0;
        we <= 1'b0;
        if (rst) begin
            st <= IDLE;
            kind_q <= 2'd0;
            clr_left <= 7'd0;
            ptr <= '0;
        end else case (st)
            IDLE: if (in_valid) begin
                vl <= in_l; vr <= in_r;
                t <= kind; m <= mix;
                kind_q <= kind;
                u <= 3'd0; k <= 3'd0;
                if (kind == 2'd0 || newk || clr_left != 7'd0) begin
                    out_valid <= 1'b1;                  // dry
                    out_l <= in_l; out_r <= in_r;
                end
                if (kind != 2'd0 && newk) begin
                    chunk <= 6'd0; clr_left <= CLEAR - 7'd1;
                    ci <= 8'd0; ptr <= '0;
                    for (int i = 0; i < 8; i++) lp[i] <= '0;
                    st <= CLR;
                end else if (kind != 2'd0 && clr_left != 7'd0) begin
                    chunk <= 6'd0 - clr_left[5:0]; clr_left <= clr_left - 7'd1;
                    ci <= 8'd0;
                    st <= CLR;
                end else if (kind != 2'd0) begin
                    st <= PD;
                end
            end
            CLR: begin
                we <= 1'b1; waddr <= {chunk, ci}; wdata <= '0;
                ci <= ci + 8'd1;
                if (ci == 8'd255) st <= IDLE;
            end
            PD: begin
                u <= u + 3'd1;
                case (u)
                    3'd0: begin
                        raddr <= ptr + RV_PD_BASE + rv_pre(t);
                        we <= 1'b1; waddr <= ptr + RV_PD_BASE;
                        wdata <= sat20((vl + vr) >>> 2);
                    end
                    3'd2: begin d <= rdata; u <= 3'd0; st <= AP; end
                    default: ;
                endcase
            end
            AP: begin
                u <= u + 3'd1;
                case (u)
                    3'd0: raddr <= ptr + rv_ap_base(k[1:0]) + rv_ap_len(k[1:0]);
                    3'd2: begin wm <= rdata; ma <= rdata; mc <= {1'b0, rv_ap_g(k[1:0])}; end
                    3'd4: begin
                        we <= 1'b1; waddr <= ptr + rv_ap_base(k[1:0]);
                        wdata <= sat20(d + tqp);
                        ma <= sat20(d + tqp);
                    end
                    3'd6: begin
                        d <= wm - tqp;
                        u <= 3'd0; k <= k + 3'd1;
                        if (k == 3'd3) begin k <= 3'd0; st <= LN; end
                    end
                    default: ;
                endcase
            end
            LN: begin
                u <= u + 3'd1;
                case (u)
                    3'd0: raddr <= ptr + rv_line_base(k) + rv_len({t, k});
                    3'd2: begin ma <= rdata - lp[k]; mc <= {1'b0, rv_damp(t)}; end
                    3'd4: begin
                        lp[k] <= lp_next[19:0];
                        u <= 3'd0; k <= k + 3'd1;
                        if (k == 3'd7) st <= WHT;
                    end
                    default: ;
                endcase
            end
            WHT: begin
                for (int i = 0; i < 8; i++) h[i] <= h3[i];
                st <= WR;
            end
            WR: begin
                u <= u + 3'd1;
                case (u)
                    3'd0: begin ma <= h[k]; mc <= {1'b0, rv_gain({t, k})}; end
                    3'd2: begin
                        we <= 1'b1; waddr <= ptr + rv_line_base(k);
                        wdata <= sat20(RV_SIGN_NEG[k] ? tqp - inj : tqp + inj);
                        u <= 3'd0; k <= k + 3'd1;
                        if (k == 3'd7) st <= OUT;
                    end
                    default: ;
                endcase
            end
            OUT: begin
                u <= u + 3'd1;
                case (u)
                    3'd0: begin ma <= h[1]; mc <= {1'b0, rv_mix({t, m})}; end
                    3'd2: begin wl <= rqp; ma <= h[2]; end
                    3'd4: begin
                        out_valid <= 1'b1;
                        out_l <= sat22(vl + wl);
                        out_r <= sat22(vr + rqp);
                        ptr <= ptr - 14'd1;
                        st <= IDLE;
                    end
                    default: ;
                endcase
            end
            default: st <= IDLE;
        endcase
    end
endmodule
