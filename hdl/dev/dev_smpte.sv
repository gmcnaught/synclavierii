// SMPTE reader, D70 subsystem 8, fed from MIDI Time Code (M20;
// docs/devices/smpte.md; sim/devices/smpte.py SmpteReader, the same
// integer algorithm, so lockstep reads match):
//
//   D70  write: subsystem select (8 selects the reader); read with 8
//        selected: 8 | 256 (data available)
//   D71  read: status << 8 | bit (0-79 in the frame being read); status
//        "200" no sync, "004" drop frame. Writes (frame mode opcodes) are
//        accepted and ignored.
//   D72  read: seconds << 8 | frames of the last complete frame
//   D73  read: hours << 8 | minutes; the read latches the next reading
//
// rdata is 0 unless the reader is present and selected (dev_midi.sv answers
// the other selects; the core ORs the two). The time code comes from every
// MIDI in byte (rx_valid/rx_data): quarter frames F1 0nnn dddd, eight in
// order give the time of piece 0, the reader then stands at that frame + 1,
// quarter 3, and moves a quarter per quarter frame in order; the full-frame
// SysEx F0 7F id 01 01 hh mm ss ff F7 locates it (invalid until eight
// pieces again). No quarter frame for LIMIT_NS: invalid. Between quarter
// frames the bit advances 20 per last quarter-frame period, in simulated
// time (tick/tick_ns), at most to the quarter's last bit.
module dev_smpte #(
    parameter int LIMIT_NS = 50_000_000
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        present,      // reader installed

    input  logic        sel,          // a D70-D73 access this clock (one clock)
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D70, 1 D71, 2 D72, 3 D73
    input  logic [15:0] wdata,
    output logic [15:0] rdata,

    input  logic        tick,         // simulated time
    input  logic [9:0]  tick_ns,

    input  logic        rx_valid,     // a byte from MIDI in
    input  logic [7:0]  rx_data
);
    typedef struct packed {
        logic [4:0] h;
        logic [5:0] m;
        logic [5:0] s;
        logic [4:0] f;
    } tc_t;

    function automatic tc_t next_frame(input tc_t t, input logic [1:0] rate);
        tc_t n;
        logic [4:0] last;
        n = t;
        last = rate == 2'd0 ? 5'd23 : rate == 2'd1 ? 5'd24 : 5'd29;
        if (t.f < last) n.f = t.f + 5'd1;
        else begin
            n.f = 5'd0;
            if (t.s < 6'd59) n.s = t.s + 6'd1;
            else begin
                n.s = 6'd0;
                if (t.m < 6'd59) n.m = t.m + 6'd1;
                else begin
                    n.m = 6'd0;
                    n.h = t.h < 5'd23 ? t.h + 5'd1 : 5'd0;
                end
            end
            if (rate == 2'd2 && n.s == 6'd0 && n.m != 6'd0 && n.m != 6'd10 && n.m != 6'd20 &&
                n.m != 6'd30 && n.m != 6'd40 && n.m != 6'd50)
                n.f = 5'd2;                       // drop frame: no frames 0, 1
        end
        return n;
    endfunction

    // ------------------------------------------------------------ registers
    logic        sel8;
    logic [15:0] info1, info2, info3;
    wire         here = present && sel8;
    wire         acc  = sel && (rd || wr);

    always_comb begin
        rdata = 16'd0;
        if (here)
            case (reg_sel)
                2'd0: rdata = 16'o410;            // 8 | data available
                2'd1: rdata = info1;
                2'd2: rdata = info2;
                default: rdata = info3;
            endcase
    end

    // ------------------------------------------------------------ decoder
    logic        qf;                  // F1 seen: data byte next
    logic [3:0]  sx;                  // SysEx data bytes seen + 1 (0: none)
    logic        sx_ok;               // 7F, id, 01, 01 so far
    logic [6:0]  sx_hh;
    logic [5:0]  sx_mm, sx_ss;
    logic [3:0]  nib [8];
    logic [7:0]  got;
    logic [2:0]  last;
    logic        valid;
    logic [1:0]  rate;
    tc_t         cur, prev;
    logic [1:0]  quarter;
    logic [25:0] elapsed, period;
    logic [4:0]  frac;
    logic [26:0] facc;

    // time, as SmpteReader.tick (a quarter frame in the same clock comes after)
    wire  [25:0] el_t = elapsed < 26'(LIMIT_NS) ?
                        (elapsed + 26'(tick_ns) < 26'(LIMIT_NS) ? elapsed + 26'(tick_ns) : 26'(LIMIT_NS))
                        : elapsed;
    wire  [26:0] fa_t = facc + 27'(tick_ns) * 27'd20;

    // a quarter frame's data byte
    wire  [2:0]  piece = rx_data[6:4];
    wire  [3:0]  qn    = rx_data[3:0];
    wire         in_order = piece == 3'd0 || piece == last + 3'd1;
    wire  [7:0]  got_n = (in_order && piece != 3'd0 ? got : 8'd0) | (8'd1 << piece);
    wire         valid_q = in_order ? valid : 1'b0;
    wire  [1:0]  rate_a = qn[2:1];
    tc_t         t0;
    assign t0 = {qn[0], nib[6], nib[5][1:0], nib[4], nib[3][1:0], nib[2], nib[1][0], nib[0]};
    tc_t         ff;                  // the full frame's time (ff: this byte)
    assign ff = {sx_hh[4:0], sx_mm, sx_ss, rx_data[4:0]};
    wire         ok_now = valid && elapsed < 26'(LIMIT_NS);

    always_ff @(posedge clk) begin
        if (rst) begin
            sel8 <= 1'b0;
            info1 <= 16'o100000; info2 <= '0; info3 <= '0;
            qf <= 1'b0; sx <= '0; sx_ok <= 1'b0; sx_hh <= '0; sx_mm <= '0; sx_ss <= '0;
            for (int i = 0; i < 8; i++) nib[i] <= '0;
            got <= '0; last <= 3'd7; valid <= 1'b0; rate <= 2'd3;
            cur <= '0; prev <= '0; quarter <= '0;
            elapsed <= 26'(LIMIT_NS); period <= '0; frac <= '0; facc <= '0;
        end else begin
            if (acc && wr && reg_sel == 2'd0) sel8 <= wdata == 16'd8;
            if (here && acc && rd && reg_sel == 2'd3) begin          // latch the next reading
                info1 <= {ok_now ? 1'b0 : 1'b1, 4'd0, rate == 2'd2, 2'd0,
                          8'({quarter, 4'd0}) + 8'({quarter, 2'd0}) + 8'(frac)};
                info2 <= {2'd0, prev.s, 3'd0, prev.f};
                info3 <= {3'd0, prev.h, 2'd0, prev.m};
            end

            if (tick) begin
                elapsed <= el_t;
                if (period != 26'd0 && frac < 5'd19) begin
                    if (fa_t >= 27'(period)) begin
                        frac <= frac + 5'd1;
                        facc <= fa_t - 27'(period);
                    end else
                        facc <= fa_t;
                end
            end

            if (rx_valid && rx_data < 8'hf8) begin
                if (rx_data[7]) begin
                    qf <= rx_data == 8'hf1;
                    sx <= rx_data == 8'hf0 ? 4'd1 : 4'd0;
                end else if (qf) begin
                    qf <= 1'b0;
                    period <= tick ? el_t : elapsed;
                    elapsed <= '0; frac <= '0; facc <= '0;
                    last <= piece;
                    nib[piece] <= qn;
                    got <= got_n;
                    valid <= valid_q;
                    if (piece == 3'd7 && got_n == 8'hff) begin
                        rate <= rate_a;
                        prev <= t0;
                        cur <= next_frame(t0, rate_a);
                        quarter <= 2'd3;
                        valid <= 1'b1;
                    end else if (valid_q) begin
                        quarter <= quarter + 2'd1;
                        if (quarter == 2'd3) begin
                            prev <= cur;
                            cur <= next_frame(cur, rate);
                        end
                    end
                end else if (sx != 4'd0 && sx < 4'd9) begin
                    sx <= sx + 4'd1;
                    case (sx)
                        4'd1: sx_ok <= rx_data == 8'h7f;
                        4'd3, 4'd4: sx_ok <= sx_ok && rx_data == 8'h01;
                        4'd5: sx_hh <= rx_data[6:0];
                        4'd6: sx_mm <= rx_data[5:0];
                        4'd7: sx_ss <= rx_data[5:0];
                        default: ;
                    endcase
                    if (sx == 4'd8 && sx_ok) begin                   // full frame
                        sx <= '0;
                        rate <= sx_hh[6:5];
                        cur <= ff;
                        prev <= ff;
                        quarter <= '0;
                        valid <= 1'b0;
                        got <= '0;
                    end
                end
            end
        end
    end
endmodule
