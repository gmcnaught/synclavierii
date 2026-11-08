// FM voice engine (M5): the integer voice model of sim/voice.py.
//
// Per channel an oscillator: per tick of OSC_CLOCK = 656015360/123 Hz
// (5.3335 MHz) of simulated time, accumulator += increment (INC + 1),
// modulus divisor (256 - NNU + INC >> 3); each wrap is a pulse; one pulse
// in 2^(7 - ONU) steps the 8-bit point. All channels are advanced in closed
// form at every system tick, so they are always at the current simulated
// time; a pitch write changes the parameters from then on (Python advances
// the channel to the write time first: the same thing).
//
// Samples at Python's render instants: start + floor(k x 1e9 / 192000) ns
// (48 kHz x 4). When one falls inside a tick [T0, T1), the oscillators are
// advanced to it first, a snapshot is taken, then they go on to T1. The
// envelope/index values are the interpolators' before or after their
// clock in this tick, by whether the clock comes at or before the sample
// instant (as Python's lazy advance). For each voice v (channels 2v, 2v+1):
//   offset = (SINE[mod point] x index) >> (8 - shift) & 255
//   w      = WAVE[TIM & 31][(car point + offset) & 255]
//   s      = (w - 128) x envelope x VOL
//   left  += s x (256 - pan), right += s x pan      (pan = ISHC & 374)
// = sim/voice.py FMSynth.sample_int. The 8 voices are summed one per clock
// from the snapshot; FM interface accesses wait meanwhile (`busy`), so a
// wave-memory write cannot land in the middle.
module fm_voices #(
    parameter int VOICES = 8
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        tick,
    input  logic [9:0]  tick_ns,

    input  logic [7:0]  ch_inc [2*VOICES],
    input  logic [7:0]  ch_nnu [2*VOICES],
    input  logic [7:0]  ch_onu [2*VOICES],
    input  logic [7:0]  ch_tim [2*VOICES],
    input  logic [7:0]  ch_f13 [2*VOICES],
    input  logic [7:0]  ch_env [2*VOICES],       // interpolator values now
    input  logic [7:0]  ch_env_next [2*VOICES],  // after this tick's interpolator clock
    input  logic [17:0] fm_rem,                  // interpolator clock phase (x 24 ns)
    output logic [12:0] wave_addr,
    input  logic [7:0]  wave_q,
    output logic        busy,

    output logic        audio_valid,
    output logic signed [39:0] audio_l,
    output logic signed [39:0] audio_r,

    input  logic        ld_we,                   // state load (simulation)
    input  logic [5:0]  ld_addr,                 // 0-15 channel {acc, pre, point};
    input  logic [63:0] ld_data                  // 32 rr, 33 {phase, to_next}
);
    `include "sine_rom.svh"

    localparam int NCH = 2 * VOICES;
    localparam logic [39:0] OSC_NUM = 40'd656015360;      // ticks per ns = NUM / D
    localparam logic [39:0] OSC_D   = 40'd123000000000;

    logic [8:0]  acc [NCH];
    logic [6:0]  pre [NCH];
    logic [7:0]  point [NCH];
    logic [39:0] rr;                    // (time x NUM) mod D
    logic [13:0] to_next;               // ns from now to the next sample instant
    logic [1:0]  phase;                 // index of that sample mod 3

    // ------------------------------------------------- oscillator advance
    function automatic logic [2:0] osc_n(input logic [39:0] x);
        osc_n = 3'd0;
        for (int k = 1; k <= 7; k++)
            if (x >= OSC_D * 40'(k)) osc_n = 3'(k);
    endfunction

    typedef struct packed {
        logic [8:0] acc;
        logic [6:0] pre;
        logic [7:0] point;
    } osc_t;

    function automatic osc_t advance(input int c, input logic [2:0] n);
        logic [8:0]  inc, dv;
        logic [11:0] sum, pulses;
        logic [12:0] t;
        logic [2:0]  sh;
        inc = 9'(ch_inc[c]) + 9'd1;
        dv  = 9'd256 - 9'(ch_nnu[c]) + 9'(ch_inc[c][7:3]);
        // acc % dv: a pitch write since the last tick may have left the
        // accumulator above the new divisor (Python's set: acc %= divisor);
        // every instruction ticks, so this is the first use after the write
        sum = 12'(acc[c] % dv) + 12'(n) * 12'(inc);
        pulses = sum / 12'(dv);
        advance.acc = 9'(sum % 12'(dv));
        sh = 3'd7 - ch_onu[c][2:0];
        t = 13'(pre[c]) + 13'(pulses);
        advance.pre = pulses == 12'd0 ? pre[c] : 7'(t & ((13'd1 << sh) - 13'd1));
        advance.point = pulses == 12'd0 ? point[c] : point[c] + 8'(t >> sh);
    endfunction

    // ------------------------------------------------------------ sampling
    wire        sample_now = tick && to_next < 14'(tick_ns);
    wire [9:0]  d = to_next[9:0];                         // offset in this tick
    wire [39:0] x_all = rr + OSC_NUM * 40'(tick_ns);
    wire [39:0] x_a   = rr + OSC_NUM * 40'(d);
    wire [2:0]  n_all = osc_n(x_all);
    wire [2:0]  n_a   = osc_n(x_a);
    wire [39:0] rr_all = x_all - OSC_D * 40'(n_all);
    wire [39:0] rr_a   = x_a - OSC_D * 40'(n_a);
    wire        env_after = 18'(fm_rem) + 18'(d) * 18'd24 >= 18'd125000;
    wire [13:0] period = phase == 2'd2 ? 14'd5209 : 14'd5208;

    logic        finish;                // second half of a sampled tick
    logic [9:0]  rest_ns;
    logic [7:0]  env_s [NCH];
    // snapshot for the mix
    logic [7:0]  sp_mod [VOICES], sp_car [VOICES], sp_idx [VOICES], sp_env [VOICES];
    logic [7:0]  sp_f13m [VOICES], sp_vol [VOICES];
    logic [4:0]  sp_tim [VOICES];
    logic        mixing;
    logic [3:0]  v;                     // voice whose wave read is in flight
    logic        rd_valid;
    logic signed [39:0] sum_l, sum_r;

    // FM accesses never coincide with a tick, so the registered phases suffice
    assign busy = finish || mixing;

    // wave address for voice v
    wire [7:0] m_sample = sine_rom(sp_mod[v[2:0]]);
    wire [15:0] prod = 16'(m_sample) * 16'(sp_idx[v[2:0]]);
    wire [1:0]  shift = sp_f13m[v[2:0]][1:0];
    wire [7:0]  offset = 8'(prod >> (4'd8 - 4'(shift)));
    assign wave_addr = {sp_tim[v[2:0]], sp_car[v[2:0]] + offset};

    // the voice whose wave byte arrives now (read issued last clock)
    logic [2:0] vq;
    wire signed [8:0]  w = $signed({1'b0, wave_q}) - 9'sd128;
    wire signed [25:0] s = 26'(w) * $signed({18'd0, sp_env[vq]}) * $signed({18'd0, sp_vol[vq]});
    wire [7:0]  pan = sp_f13m[vq] & 8'o374;
    wire signed [39:0] add_r = 40'(s) * $signed({32'd0, pan});
    wire signed [39:0] add_l = 40'(s) * $signed(40'd256 - {32'd0, pan});

    always_ff @(posedge clk) begin
        audio_valid <= 1'b0;
        if (rst) begin
            finish <= 1'b0;
            mixing <= 1'b0;
            rd_valid <= 1'b0;
            if (ld_we) begin
                if (ld_addr < 6'd16)
                    {acc[ld_addr[3:0]], pre[ld_addr[3:0]], point[ld_addr[3:0]]} <= ld_data[23:0];
                else if (ld_addr == 6'd32) rr <= ld_data[39:0];
                else if (ld_addr == 6'd33) {phase, to_next} <= ld_data[15:0];
            end
        end else begin
            if (sample_now) begin
                // to the sample instant; envelopes as of that instant
                for (int c = 0; c < NCH; c++) begin
                    osc_t o;
                    o = advance(c, n_a);
                    acc[c] <= o.acc; pre[c] <= o.pre; point[c] <= o.point;
                    env_s[c] <= env_after ? ch_env_next[c] : ch_env[c];
                end
                rr <= rr_a;
                rest_ns <= tick_ns - d;
                finish <= 1'b1;
                to_next <= to_next + period - 14'(tick_ns);
                phase <= phase == 2'd2 ? 2'd0 : phase + 2'd1;
            end else if (finish) begin
                // snapshot at the sample instant, then on to the end of the tick
                for (int k = 0; k < VOICES; k++) begin
                    sp_mod[k] <= point[2*k];
                    sp_car[k] <= point[2*k+1];
                    sp_idx[k] <= env_s[2*k];
                    sp_env[k] <= env_s[2*k+1];
                    sp_f13m[k] <= ch_f13[2*k];
                    sp_vol[k] <= ch_f13[2*k+1];
                    sp_tim[k] <= ch_tim[2*k+1][4:0];
                end
                for (int c = 0; c < NCH; c++) begin
                    osc_t o;
                    o = advance(c, osc_n(rr + OSC_NUM * 40'(rest_ns)));
                    acc[c] <= o.acc; pre[c] <= o.pre; point[c] <= o.point;
                end
                rr <= rr + OSC_NUM * 40'(rest_ns) - OSC_D * 40'(osc_n(rr + OSC_NUM * 40'(rest_ns)));
                finish <= 1'b0;
                mixing <= 1'b1;
                v <= 4'd0;
                rd_valid <= 1'b0;
                sum_l <= 40'sd0;
                sum_r <= 40'sd0;
            end else if (tick) begin
                for (int c = 0; c < NCH; c++) begin
                    osc_t o;
                    o = advance(c, n_all);
                    acc[c] <= o.acc; pre[c] <= o.pre; point[c] <= o.point;
                end
                rr <= rr_all;
                to_next <= to_next - 14'(tick_ns);
            end

            if (mixing) begin
                // one wave read per clock; the byte for voice vq arrives a clock later
                if (rd_valid) begin
                    sum_l <= sum_l + add_l;
                    sum_r <= sum_r + add_r;
                end
                if (v < 4'(VOICES)) begin
                    vq <= v[2:0];
                    rd_valid <= 1'b1;
                    v <= v + 4'd1;
                end else begin
                    mixing <= 1'b0;
                    rd_valid <= 1'b0;
                    audio_valid <= 1'b1;
                    audio_l <= sum_l + (rd_valid ? add_l : 40'sd0);
                    audio_r <= sum_r + (rd_valid ? add_r : 40'sd0);
                end
            end
        end
    end
endmodule
