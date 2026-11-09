// D160-D163 FM interface and the FM voice engine (sim/devices/synth.py
// FMInterface, sim/fm.py, sim/voice.py FMSynth), for up to MAXV voices
// (2 x MAXV channels); the number present, `nvoices` (8 unless a state
// image says otherwise: device 5 index 16), is what D160 bit 0 reports.
//
// CPU side:
//   D160 write: channel word (low 8 bits = channel); D161 write: function;
//   D162 write: data to (channel, function). D163 write: 1 toggles the
//   external clock output, xxx10 selects A/D channel bits 4-2.
//   D160 read: switches (bits 7-2) | external clock in (bit 1) | bit 0 =
//     channel present (channel < 2 x nvoices), cleared while function 12 is
//     selected and the channel's interpolator is at its limit.
//   D163 read: the selected A/D value. D161/D162 reads: no SYN when strict.
// Per channel: pitch (0 INC, 1 NNU, 2 ONU), TIM (4), function 13 (ISHC /
// VOL), the interpolator (10 divisor, 11 adder, 12 limit) and a wave
// memory address (6 zero, 7 store byte + increment) into 32 x 256 bytes.
//
// Engine. Channel state is in RAMs, even and odd channels apart, so a
// voice (channels 2v, 2v+1) is one RAM address. Work is done one voice a
// clock, in passes over the voices:
//   sample instant (start + floor(k x 1e9 / 192000) ns, 48 kHz x 4):
//     every oscillator and interpolator advanced to the instant, then the
//     voices mixed:
//       offset = (SINE[mod point] x index) >> (8 - shift) & 255
//       w      = WAVE[TIM & 31][(car point + offset) & 255]
//       s      = (w - 128) x envelope x VOL
//       left  += s x (256 - pan), right += s x pan    (pan = ISHC & 374)
//     = FMSynth.sample_int;
//   catch-up before a pitch or interpolator write (functions 0-2, 10-12)
//     and before a D160 read with function 12: that voice advanced to now
//     with the old settings (FMSynth.write and FMInterface advance the
//     channel first).
// Oscillators (OSC_CLOCK = 656015360/123 Hz ticks): G counts the ticks
// since the last sample instant; a channel holds `applied`, the ticks of G
// it has already had (from a catch-up), and gets G - applied at the next
// pass. The closed form (accumulator += n x (INC + 1) mod divisor, one
// point step per 2^(7 - ONU) wraps) gives the same state however the ticks
// are split, so this is exactly Python's lazy advance. Interpolators the
// same way: their 192 kHz clocks (tick/tick_ns, 24 / 125000 per ns) are
// counted (mod 4), each channel keeps the count it has had, and a pass or
// catch-up applies the difference with sim/fm.py Interpolator.advance_to's
// closed form (a clock at the sample instant counts as before it). So one
// pass per 5.2 us does all the work: about 40 clocks for 32 voices, of the
// 83 a 16 MHz MiSTer clock has. CPU accesses to D160-D163 wait while the
// engine has work (no simulated time passes); the CPU itself waits
// (`stall`) only if a sample instant arrives while the last is still being
// done.
(* multstyle = "logic" *)       // small multiplies: keep the DSP blocks for sys/
module dev_fm #(
    parameter int MAXV = 32
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0-3: D160-D163
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        nosyn,
    input  logic        strict,
    input  logic        tick,
    input  logic [9:0]  tick_ns,
    output logic        stall,        // CPU: wait before the next fetch

    output logic        audio_valid,
    output logic signed [39:0] audio_l,
    output logic signed [39:0] audio_r,

    input  logic        ld_we,        // state load (simulation, state images), sim/lockstep.py:
    input  logic        ld_wave,      //   device 5 (ld_wave = 0) or 6 (wave memory byte)
    input  logic [12:0] ld_addr,
    input  logic [31:0] ld_data,
    input  logic        ld_voice_we,  // voice engine: 0-15 channel {acc, pre, point},
    input  logic [5:0]  ld_voice_addr,//   32 rr, 33 {phase, to_next}
    input  logic [63:0] ld_voice_data
);
    `include "sine_rom.svh"

    localparam int VB = $clog2(MAXV);                     // voice (RAM address) bits
    localparam logic [39:0] OSC_NUM = 40'd656015360;      // ticks per ns = NUM / D
    localparam logic [39:0] OSC_D   = 40'd123000000000;

    // ------------------------------------------------------- CPU registers
    logic [15:0] channel_word, function_;
    logic [7:0]  switches;
    logic        ext_in, ext_out;
    logic [15:0] adc [8];
    logic [2:0]  adc_select;
    logic [17:0] rem;                           // (time x 24) mod 125000
    logic [5:0]  nvoices;
    logic [7:0]  wave [8192] /* verilator public */;   // public: board bench reads it

    wire [7:0] ch = channel_word[7:0];
    wire       ch_ok = {1'b0, ch} < {2'b0, nvoices, 1'b0};
    wire       cb = ch[0];                      // bank of the CPU's channel
    wire [VB-1:0] ca = ch[VB:1];

    // ---------------------------------------------------------------- RAMs
    // P (written by the CPU): 0 INC, 1 NNU, 2 ONU, 3 TIM, 4 f13, 5 div, 6 add, 7 limit
    // S (written by the engine): 0 value, 1 interp prescale, 2 interp acc,
    //   3 osc point, 4 osc prescale, 5 osc acc (9 bits), 6 applied ticks,
    //   7 applied interpolator clocks (mod 4)
    // C (CPU-side copies, read at the CPU's channel): 0 value, 1 limit, 2 TIM, 3 MAR
    logic          p_we [2][8], s_we [2][8], c_we [2][4];
    logic [VB-1:0] p_wa [2], s_wa [2], c_wa [2];
    logic [7:0]    p_wd [2][8], c_wd [2][4];
    logic [8:0]    s_wd [2][8];
    logic [VB-1:0] e_ra;                        // engine read address (voice)
    logic [7:0]    p_q [2][8], c_q [2][4];
    logic [8:0]    s_q [2][8];
    genvar gb, gf;
    generate for (gb = 0; gb < 2; gb++) begin : g_bank
        for (gf = 0; gf < 8; gf++) begin : g_p
            fm_ram #(.W(8), .A(VB)) p (.clk, .we(p_we[gb][gf]), .wa(p_wa[gb]), .wd(p_wd[gb][gf]),
                                       .ra(e_ra), .q(p_q[gb][gf]));
        end
        for (gf = 0; gf < 8; gf++) begin : g_s
            fm_ram #(.W(9), .A(VB)) s (.clk, .we(s_we[gb][gf]), .wa(s_wa[gb]), .wd(s_wd[gb][gf]),
                                       .ra(e_ra), .q(s_q[gb][gf]));
        end
        for (gf = 0; gf < 4; gf++) begin : g_c
            fm_ram #(.W(8), .A(VB)) c (.clk, .we(c_we[gb][gf]), .wa(c_wa[gb]), .wd(c_wd[gb][gf]),
                                       .ra(ca), .q(c_q[gb][gf]));
        end
    end endgenerate
    wire [7:0] c_val = c_q[cb][0], c_lim = c_q[cb][1], c_tim = c_q[cb][2], c_mar = c_q[cb][3];

    // ------------------------------------------------------------- engine
    typedef enum logic [1:0] { M_SAMPLE, M_CATCH } mode_t;
    logic          clearing;
    logic [VB:0]   clr_a;
    logic          running;
    mode_t         mode;
    logic [VB:0]   issue_v;                     // next voice to issue
    logic [VB:0]   n_issue;                     // voices in this pass
    logic [5:0]    base;                        // ticks to bring each oscillator up to
    logic          pend_s;                      // a sample instant not yet done
    logic [5:0]    pend_g;                      // ticks of G up to the pending sample instant
    logic [1:0]    icount;                      // interpolator clocks so far (mod 4)
    logic [1:0]    pend_ic, ibase;              // ... up to the pending sample instant, this pass's
    logic [5:0]    g;                           // oscillator ticks since the last sample instant
    logic [1:0]    settle;                      // clocks until the C copies are current
    logic          caught;                      // the held pitch write's catch-up is done

    // sample instants
    logic [39:0] rr;                            // (time x NUM) mod D
    logic [13:0] to_next;                       // ns from now to the next sample instant
    logic [1:0]  phase;                         // index of that sample mod 3
    function automatic logic [2:0] osc_n(input logic [39:0] x);
        osc_n = 3'd0;
        for (int k = 1; k <= 7; k++)
            if (x >= OSC_D * 40'(k)) osc_n = 3'(k);
    endfunction
    wire        sample_now = tick && to_next < 14'(tick_ns);
    wire [9:0]  d = to_next[9:0];                         // offset in this tick
    wire [39:0] x_all = rr + OSC_NUM * 40'(tick_ns);
    wire [39:0] x_a   = rr + OSC_NUM * 40'(d);
    wire [2:0]  n_all = osc_n(x_all);
    wire [2:0]  n_a   = osc_n(x_a);
    wire [39:0] rr_all = x_all - OSC_D * 40'(n_all);
    wire [39:0] rr_a   = x_a - OSC_D * 40'(n_a);
    wire [13:0] period = phase == 2'd2 ? 14'd5209 : 14'd5208;
    logic        finish;                                  // rest of a sampled tick
    logic [9:0]  rest_ns;
    wire  [39:0] x_rest  = rr + OSC_NUM * 40'(rest_ns);
    wire  [2:0]  n_rest  = osc_n(x_rest);
    wire  [39:0] rr_rest = x_rest - OSC_D * 40'(n_rest);

    wire [17:0] rem_next = rem + 18'(tick_ns) * 18'd24;   // up to 148,975: 18 bits
    wire        interp_now = tick && rem_next >= 18'd125000;
    wire        interp_first = 18'(rem) + 18'(d) * 18'd24 >= 18'd125000;   // at or before the instant

    wire   busy = clearing || running || pend_s || finish || settle != 2'd0;
    assign stall = running && pend_s;

    // ------------------------------------------------------------ CPU side
    wire pitch_fn = function_ == 16'o0 || function_ == 16'o1 || function_ == 16'o2;
    wire interp_fn = function_ == 16'o10 || function_ == 16'o11 || function_ == 16'o12;
    wire need_catch = sel && ch_ok && ((wr && reg_sel == 2'd2 && (pitch_fn || interp_fn))
                                       || (rd && reg_sel == 2'd0 && function_ == 16'o12));
    wire bit0 = ch_ok && !(function_ == 16'o12 && c_val == c_lim);
    assign nosyn = sel && rd && strict && (reg_sel == 2'd1 || reg_sel == 2'd2);
    assign ack   = sel && !nosyn && !busy && (!need_catch || caught);
    always_comb begin
        case (reg_sel)
            2'd0: rdata = {8'd0, switches & 8'o374} | {14'd0, ext_in, bit0};
            2'd3: rdata = adc[adc_select];
            default: rdata = 16'd0;
        endcase
    end
    wire cpu_w = ack && wr && reg_sel == 2'd2 && ch_ok;

    // ----------------------------------------------------------- pipeline
    // B: RAM outputs for the voice issued last clock
    logic          vb_ok, vc_ok, vd_ok, ve_ok, vf_ok, vg_ok, vh_ok;
    logic [VB-1:0] vb_a, vc_a, vd_a;
    // interpolators: the clocks they have not had yet, per bank. Stage B
    // divides (prescaler pulses), stage C multiplies and clamps; none due:
    // unchanged, as advance_to returns early.
    logic [8:0] b_pulses [2], b_pre [2];
    always_comb
        for (int b = 0; b < 2; b++) begin
            logic [8:0] dd, total;
            dd    = 9'd256 - {1'b0, p_q[b][5]};
            total = {1'b0, s_q[b][1][7:0]} + 9'(2'(ibase - s_q[b][7][1:0]));
            b_pulses[b] = total / dd;
            b_pre[b]    = 9'(total % dd);
        end
    logic       ci_none [2];                     // no clock due: keep the state
    logic [8:0] ci_pulses [2], ci_pre [2], ci_acc [2], ci_val [2], ci_opre [2];
    logic [7:0] ci_add [2], ci_lim [2];
    logic [8:0] i_val [2], i_pre [2], i_acc [2];
    always_comb
        for (int b = 0; b < 2; b++) begin
            logic [16:0] sum;
            logic [9:0]  steps;
            logic [7:0]  val, lim;
            sum   = {9'd0, ci_acc[b][7:0]} + 17'(ci_pulses[b]) * (17'(ci_add[b]) + 17'd1);
            steps = {1'b0, sum[16:8]};
            val   = ci_val[b][7:0];
            lim   = ci_lim[b];
            if (ci_none[b]) begin
                i_pre[b] = ci_opre[b];
                i_acc[b] = ci_acc[b];
                i_val[b] = ci_val[b];
            end else begin
                i_pre[b] = ci_pre[b];
                i_acc[b] = ci_pulses[b] == 9'd0 ? ci_acc[b] : {1'b0, sum[7:0]};
                if (val < lim)
                    i_val[b] = 10'(val) + steps >= 10'(lim) ? 9'(lim) : 9'(val + steps[7:0]);
                else if (val > lim)
                    i_val[b] = 10'(lim) + steps >= 10'(val) ? 9'(lim) : 9'(val - steps[7:0]);
                else
                    i_val[b] = 9'(val);
            end
        end

    // oscillator advance: B operands, C acc mod divisor, X and Y the two
    // halves of (acc + n x increment) / divisor (restoring division, one
    // clock each, for a 50 MHz clock), D the new prescale and point
    logic [8:0]  c_acc [2], c_dv [2], xs_a [2], x_dv [2], y_dv [2];
    logic [14:0] c_m [2], x_m [2];
    logic [2:0]  c_sh [2], x_sh [2], y_sh [2], d_sh [2];
    logic [7:0]  c_opre [2], c_opt [2], x_opre [2], x_opt [2], y_opre [2], y_opt [2], d_opre [2], d_opt [2];
    logic [6:0]  y_qh [2];
    logic [8:0]  y_r [2];
    logic [7:0]  y_lo [2];
    logic [14:0] d_pulses [2];
    logic [8:0]  d_acc [2];
    logic [8:0]  x_keep [2][3], y_keep [2][3], d_keep [2][3];   // value, interp prescale, interp acc
    logic [7:0]  c_f13m, c_f13k, c_timk, x_f13m, x_f13k, x_timk, y_f13m, y_f13k, y_timk;
    logic [7:0]  x_vm, x_vk, y_vm, y_vk;
    logic [7:0]  d_vm, d_vk, d_f13m, d_f13k, d_timk;
    logic [VB-1:0] vx_a, vy_a;
    logic        vx_ok, vy_ok;

    // restoring division of {hi bits, lo bits} by d: the quotient bits of
    // `bits` dividend bits, starting from remainder r (< d)
    function automatic logic [15:0] div_hi(input logic [14:0] sum, input logic [8:0] dvs);
        logic [9:0] r;
        logic [6:0] q;
        r = '0; q = '0;
        for (int i = 14; i >= 8; i--) begin
            r = {r[8:0], sum[i]};
            if (r >= {1'b0, dvs}) begin r = r - {1'b0, dvs}; q[i - 8] = 1'b1; end
        end
        div_hi = {q, r[8:0]};
    endfunction
    function automatic logic [16:0] div_lo(input logic [8:0] r0, input logic [7:0] lo, input logic [8:0] dvs);
        logic [9:0] r;
        logic [7:0] q;
        r = {1'b0, r0}; q = '0;
        for (int i = 7; i >= 0; i--) begin
            r = {r[8:0], lo[i]};
            if (r >= {1'b0, dvs}) begin r = r - {1'b0, dvs}; q[i] = 1'b1; end
        end
        div_lo = {q, r[8:0]};
    endfunction
    // mix, stages E-H
    logic [7:0]  e_pm, e_pk, e_vm, e_vk, e_f13m, e_f13k, e_timk;
    logic [7:0]  f_sine, f_pk, f_vm, f_vk, f_f13m, f_f13k, f_timk;
    logic [12:0] wave_addr;
    logic [7:0]  wave_q;
    logic [7:0]  g_vk, g_vol, g_pan;
    logic signed [25:0] h_s;
    logic [7:0]  h_pan;
    logic signed [39:0] sum_l, sum_r;
    wire  mix = mode == M_SAMPLE;

    wire [7:0]  e_point [2];
    // stage D results
    logic [7:0] dn_pre [2], dn_pt [2];
    always_comb
        for (int b = 0; b < 2; b++) begin
            logic [15:0] t;
            t = 16'(d_opre[b]) + 16'(d_pulses[b]);
            dn_pre[b] = d_pulses[b] == 15'd0 ? d_opre[b] : 8'(t & ((16'd1 << d_sh[b]) - 16'd1));
            dn_pt[b]  = d_pulses[b] == 15'd0 ? d_opt[b] : d_opt[b] + 8'(t >> d_sh[b]);
        end

    wire [15:0] f_prod = 16'(f_sine) * 16'(f_vm);
    wire [7:0]  f_off  = 8'(f_prod >> (4'd8 - 4'(f_f13m[1:0])));
    assign wave_addr = {f_timk[4:0], f_pk + f_off};
    wire signed [8:0]  g_w = $signed({1'b0, wave_q}) - 9'sd128;
    wire signed [25:0] g_s = 26'(g_w) * $signed({18'd0, g_vk}) * $signed({18'd0, g_vol});
    wire signed [39:0] h_add_r = 40'(h_s) * $signed({32'd0, h_pan});
    wire signed [39:0] h_add_l = 40'(h_s) * $signed(40'd256 - {32'd0, h_pan});

    // --------------------------------------------------- RAM write ports
    wire ld_ch  = rst && ld_we && !ld_wave && ld_addr >= 13'd32;
    wire [5:0] ld_c = 6'((ld_addr - 13'd32) >> 4);
    wire [3:0] ld_k = ld_addr[3:0];
    wire ld_osc = rst && ld_voice_we && ld_voice_addr < 6'd16;
    always_comb begin
        for (int b = 0; b < 2; b++) begin
            p_wa[b] = '0; s_wa[b] = '0; c_wa[b] = '0;
            for (int f = 0; f < 8; f++) begin p_we[b][f] = 1'b0; p_wd[b][f] = '0; end
            for (int f = 0; f < 8; f++) begin s_we[b][f] = 1'b0; s_wd[b][f] = '0; end
            for (int f = 0; f < 4; f++) begin c_we[b][f] = 1'b0; c_wd[b][f] = '0; end
        end
        if (clearing) begin
            for (int b = 0; b < 2; b++) begin
                p_wa[b] = clr_a[VB-1:0]; s_wa[b] = clr_a[VB-1:0]; c_wa[b] = clr_a[VB-1:0];
                for (int f = 0; f < 8; f++) p_we[b][f] = 1'b1;
                p_wd[b][5] = 8'd255; p_wd[b][6] = 8'd255;       // sim/fm.py Interpolator()
                for (int f = 0; f < 8; f++) s_we[b][f] = 1'b1;
                for (int f = 0; f < 4; f++) c_we[b][f] = 1'b1;
            end
        end else if (ld_ch && {1'b0, ld_c} < 7'(2 * MAXV)) begin
            automatic int b = ld_c[0];
            p_wa[b] = ld_c[VB:1]; s_wa[b] = ld_c[VB:1]; c_wa[b] = ld_c[VB:1];
            case (ld_k)
                4'd0: begin p_we[b][5] = 1'b1; p_wd[b][5] = ld_data[7:0]; end
                4'd1: begin p_we[b][6] = 1'b1; p_wd[b][6] = ld_data[7:0]; end
                4'd2: begin p_we[b][7] = 1'b1; p_wd[b][7] = ld_data[7:0];
                            c_we[b][1] = 1'b1; c_wd[b][1] = ld_data[7:0]; end
                4'd3: begin s_we[b][0] = 1'b1; s_wd[b][0] = {1'b0, ld_data[7:0]};
                            c_we[b][0] = 1'b1; c_wd[b][0] = ld_data[7:0]; end
                4'd4: begin s_we[b][1] = 1'b1; s_wd[b][1] = {1'b0, ld_data[7:0]}; end
                4'd5: begin s_we[b][2] = 1'b1; s_wd[b][2] = {1'b0, ld_data[7:0]}; end
                4'd6: begin c_we[b][3] = 1'b1; c_wd[b][3] = ld_data[7:0]; end
                4'd7: begin
                    p_we[b][0] = 1'b1; p_wd[b][0] = ld_data[31:24];
                    p_we[b][1] = 1'b1; p_wd[b][1] = ld_data[23:16];
                    p_we[b][2] = 1'b1; p_wd[b][2] = ld_data[15:8];
                    p_we[b][3] = 1'b1; p_wd[b][3] = ld_data[7:0];
                    c_we[b][2] = 1'b1; c_wd[b][2] = ld_data[7:0];
                end
                4'd8: begin p_we[b][4] = 1'b1; p_wd[b][4] = ld_data[7:0]; end
                4'd9: begin                                    // oscillator {acc, pre, point}
                    s_we[b][5] = 1'b1; s_wd[b][5] = ld_data[23:15];
                    s_we[b][4] = 1'b1; s_wd[b][4] = {2'b0, ld_data[14:8]};
                    s_we[b][3] = 1'b1; s_wd[b][3] = {1'b0, ld_data[7:0]};
                    s_we[b][6] = 1'b1; s_wd[b][6] = '0;
                end
                default: ;
            endcase
        end else if (ld_osc) begin
            automatic int b = ld_voice_addr[0];
            s_wa[b] = VB'(ld_voice_addr[5:1]);
            s_we[b][5] = 1'b1; s_wd[b][5] = ld_voice_data[23:15];
            s_we[b][4] = 1'b1; s_wd[b][4] = {2'b0, ld_voice_data[14:8]};
            s_we[b][3] = 1'b1; s_wd[b][3] = {1'b0, ld_voice_data[7:0]};
            s_we[b][6] = 1'b1; s_wd[b][6] = '0;
        end else if (running && vd_ok) begin
            for (int b = 0; b < 2; b++) begin
                s_wa[b] = vd_a; c_wa[b] = vd_a;
                c_we[b][0] = 1'b1; c_wd[b][0] = d_keep[b][0][7:0];
                s_we[b][7] = 1'b1; s_wd[b][7] = 9'(ibase);
                for (int f = 0; f < 3; f++) begin s_we[b][f] = 1'b1; s_wd[b][f] = d_keep[b][f]; end
                s_we[b][3] = 1'b1; s_wd[b][3] = {1'b0, dn_pt[b]};
                s_we[b][4] = 1'b1; s_wd[b][4] = {1'b0, dn_pre[b]};
                s_we[b][5] = 1'b1; s_wd[b][5] = d_acc[b];
                s_we[b][6] = 1'b1; s_wd[b][6] = mode == M_CATCH ? 9'(base) : 9'd0;
            end
        end else if (cpu_w) begin
            p_wa[cb] = ca; c_wa[cb] = ca;
            case (function_)
                16'o0:  begin p_we[cb][0] = 1'b1; p_wd[cb][0] = wdata[7:0]; end
                16'o1:  begin p_we[cb][1] = 1'b1; p_wd[cb][1] = wdata[7:0]; end
                16'o2:  begin p_we[cb][2] = 1'b1; p_wd[cb][2] = wdata[7:0]; end
                16'o4:  begin p_we[cb][3] = 1'b1; p_wd[cb][3] = wdata[7:0];
                              c_we[cb][2] = 1'b1; c_wd[cb][2] = wdata[7:0]; end
                16'o6:  begin c_we[cb][3] = 1'b1; c_wd[cb][3] = 8'd0; end
                16'o7:  begin c_we[cb][3] = 1'b1; c_wd[cb][3] = c_mar + 8'd1; end
                16'o10: begin p_we[cb][5] = 1'b1; p_wd[cb][5] = wdata[7:0]; end
                16'o11: begin p_we[cb][6] = 1'b1; p_wd[cb][6] = wdata[7:0]; end
                16'o12: begin p_we[cb][7] = 1'b1; p_wd[cb][7] = wdata[7:0];
                              c_we[cb][1] = 1'b1; c_wd[cb][1] = wdata[7:0]; end
                16'o13: begin p_we[cb][4] = 1'b1; p_wd[cb][4] = wdata[7:0]; end
                default: ;
            endcase
        end
    end

    // ------------------------------------------------- sequencing, events
    logic rst_d;
    always_ff @(posedge clk) begin
        rst_d <= rst;
        audio_valid <= 1'b0;
        if (rst) begin
            if (!rst_d) begin
                clearing <= 1'b1; clr_a <= '0; nvoices <= 6'd8;
            end else if (clearing) begin
                clr_a <= clr_a + 1'b1;
                if (clr_a == (VB+1)'(MAXV - 1)) clearing <= 1'b0;
            end
            running <= 1'b0; pend_s <= 1'b0; finish <= 1'b0; icount <= '0;
            settle <= '0; caught <= 1'b0; g <= '0;
            vb_ok <= 1'b0; vc_ok <= 1'b0; vx_ok <= 1'b0; vy_ok <= 1'b0; vd_ok <= 1'b0; ve_ok <= 1'b0;
            vf_ok <= 1'b0; vg_ok <= 1'b0; vh_ok <= 1'b0;
            if (ld_we && ld_wave) wave[ld_addr] <= ld_data[7:0];
            else if (ld_we && ld_addr < 13'd32) case (ld_addr[4:0])
                5'd0: channel_word <= ld_data[15:0];
                5'd1: function_ <= ld_data[15:0];
                5'd2: switches <= ld_data[7:0];
                5'd3: ext_in <= ld_data[0];
                5'd4: ext_out <= ld_data[0];
                5'd5: adc_select <= ld_data[2:0];
                5'd6: rem <= ld_data[17:0];
                5'd16: nvoices <= ld_data[5:0] > 6'(MAXV) ? 6'(MAXV) : ld_data[5:0];
                default: if (ld_addr[4:3] == 2'd1) adc[ld_addr[2:0]] <= ld_data[15:0];
            endcase
            if (ld_voice_we && ld_voice_addr == 6'd32) rr <= ld_voice_data[39:0];
            if (ld_voice_we && ld_voice_addr == 6'd33) {phase, to_next} <= ld_voice_data[15:0];
        end else begin
            // ---- CPU registers
            if (ack && wr) begin
                settle <= 2'd2;
                case (reg_sel)
                    2'd0: channel_word <= wdata;
                    2'd1: function_ <= wdata;
                    2'd2: if (ch_ok && function_ == 16'o7) wave[{c_tim[4:0], c_mar}] <= wdata[7:0];
                    default:
                        if (wdata == 16'd1) ext_out <= !ext_out;
                        else if (wdata[1:0] == 2'd2) adc_select <= wdata[4:2];
                endcase
            end else if (settle != 2'd0 && !running) settle <= settle - 2'd1;
            if (ack) caught <= 1'b0;

            // ---- passes
            vb_ok <= 1'b0;
            if (!running && !finish && settle == 2'd0) begin
                if (pend_s) begin
                    running <= 1'b1; mode <= M_SAMPLE; pend_s <= 1'b0; base <= pend_g; ibase <= pend_ic;
                    issue_v <= '0; n_issue <= (VB+1)'(nvoices);
                    sum_l <= '0; sum_r <= '0;
                end else if (need_catch && !caught) begin
                    running <= 1'b1; mode <= M_CATCH; base <= g; ibase <= icount;
                    issue_v <= (VB+1)'(ch[VB:1]); n_issue <= (VB+1)'(ch[VB:1]) + 1'b1;
                end
            end else if (running) begin
                if (issue_v < n_issue) begin
                    issue_v <= issue_v + 1'b1;
                    vb_ok <= 1'b1;
                    vb_a <= issue_v[VB-1:0];
                end else if (!vb_ok && !vc_ok && !vx_ok && !vy_ok && !vd_ok && !ve_ok && !vf_ok && !vg_ok && !vh_ok) begin
                    running <= 1'b0;
                    settle <= 2'd2;
                    if (mode == M_CATCH) caught <= 1'b1;
                    if (mode == M_SAMPLE) begin
                        audio_valid <= 1'b1;
                        audio_l <= sum_l;
                        audio_r <= sum_r;
                    end
                end
            end

            // ---- events from the CPU's ticks (after the passes: a new event wins)
            if (tick) rem <= interp_now ? rem_next - 18'd125000 : rem_next;
            if (sample_now) begin
                pend_s <= 1'b1;
                pend_g <= g + 6'(n_a);
                // interpolator clocks up to the instant (one in this tick counts
                // if it comes at or before it)
                pend_ic <= icount + 2'(interp_now && interp_first);
                rr <= rr_a;
                rest_ns <= tick_ns - d;
                finish <= 1'b1;
                to_next <= to_next + period - 14'(tick_ns);
                phase <= phase == 2'd2 ? 2'd0 : phase + 2'd1;
            end else if (finish) begin
                rr <= rr_rest;
                g <= 6'(n_rest);
                finish <= 1'b0;
            end else if (tick) begin
                rr <= rr_all;
                g <= g + 6'(n_all);
                to_next <= to_next - 14'(tick_ns);
            end
            if (interp_now) icount <= icount + 2'd1;

            // ---- B -> C: oscillator terms
            vc_ok <= vb_ok;
            vc_a <= vb_a;
            for (int b = 0; b < 2; b++) begin
                automatic logic [8:0] dv = 9'd256 - 9'(p_q[b][1]) + 9'(p_q[b][0][7:3]);
                automatic logic [5:0] n = base - s_q[b][6][5:0];
                c_dv[b] <= dv;
                c_acc[b] <= s_q[b][5];
                c_m[b]  <= 15'(n) * (15'(p_q[b][0]) + 15'd1);
                c_sh[b] <= 3'd7 - p_q[b][2][2:0];
                c_opre[b] <= s_q[b][4][7:0];
                c_opt[b]  <= s_q[b][3][7:0];
                ci_none[b] <= 2'(ibase - s_q[b][7][1:0]) == 2'd0;
                ci_pulses[b] <= b_pulses[b]; ci_pre[b] <= b_pre[b]; ci_opre[b] <= s_q[b][1];
                ci_acc[b] <= s_q[b][2]; ci_val[b] <= s_q[b][0];
                ci_add[b] <= p_q[b][6]; ci_lim[b] <= p_q[b][7];
            end

            c_f13m <= p_q[0][4]; c_f13k <= p_q[1][4]; c_timk <= p_q[1][3];

            // ---- C -> X: accumulator mod divisor; interpolators (stage C)
            vx_ok <= vc_ok; vx_a <= vc_a;
            for (int b = 0; b < 2; b++) begin
                xs_a[b] <= c_acc[b] % c_dv[b];
                x_m[b] <= c_m[b]; x_dv[b] <= c_dv[b];
                x_sh[b] <= c_sh[b]; x_opre[b] <= c_opre[b]; x_opt[b] <= c_opt[b];
                x_keep[b][0] <= i_val[b]; x_keep[b][1] <= i_pre[b]; x_keep[b][2] <= i_acc[b];
            end
            x_vm <= i_val[0][7:0]; x_vk <= i_val[1][7:0]; x_f13m <= c_f13m; x_f13k <= c_f13k; x_timk <= c_timk;

            // ---- X -> Y: quotient bits 14-8
            vy_ok <= vx_ok; vy_a <= vx_a;
            for (int b = 0; b < 2; b++) begin
                automatic logic [14:0] sum = 15'(xs_a[b]) + x_m[b];
                {y_qh[b], y_r[b]} <= div_hi(sum, x_dv[b]);
                y_lo[b] <= sum[7:0]; y_dv[b] <= x_dv[b];
                y_sh[b] <= x_sh[b]; y_opre[b] <= x_opre[b]; y_opt[b] <= x_opt[b];
                for (int f = 0; f < 3; f++) y_keep[b][f] <= x_keep[b][f];
            end
            y_vm <= x_vm; y_vk <= x_vk; y_f13m <= x_f13m; y_f13k <= x_f13k; y_timk <= x_timk;

            // ---- Y -> D: quotient bits 7-0 and the remainder
            vd_ok <= vy_ok; vd_a <= vy_a;
            for (int b = 0; b < 2; b++) begin
                automatic logic [16:0] lo = div_lo(y_r[b], y_lo[b], y_dv[b]);
                d_pulses[b] <= {y_qh[b], lo[16:9]};
                d_acc[b]    <= lo[8:0];
                d_sh[b] <= y_sh[b]; d_opre[b] <= y_opre[b]; d_opt[b] <= y_opt[b];
                for (int f = 0; f < 3; f++) d_keep[b][f] <= y_keep[b][f];
            end
            d_vm <= y_vm; d_vk <= y_vk; d_f13m <= y_f13m; d_f13k <= y_f13k; d_timk <= y_timk;

            // ---- D -> E: new points (S written at D, above)
            ve_ok <= vd_ok && mix;
            e_pm <= dn_pt[0]; e_pk <= dn_pt[1];
            e_vm <= d_vm; e_vk <= d_vk; e_f13m <= d_f13m; e_f13k <= d_f13k; e_timk <= d_timk;

            // ---- E -> F: modulator sine
            vf_ok <= ve_ok;
            f_sine <= sine_rom(e_pm);
            f_pk <= e_pk; f_vm <= e_vm; f_vk <= e_vk; f_f13m <= e_f13m; f_f13k <= e_f13k;
            f_timk <= e_timk;

            // ---- F -> G: wave read (wave_addr from F)
            vg_ok <= vf_ok;
            g_vk <= f_vk; g_vol <= f_f13k; g_pan <= f_f13m & 8'o374;

            // ---- G -> H: sample
            vh_ok <= vg_ok;
            h_s <= g_s; h_pan <= g_pan;

            // ---- H: accumulate
            if (vh_ok) begin
                sum_l <= sum_l + h_add_l;
                sum_r <= sum_r + h_add_r;
            end
        end
        wave_q <= wave[wave_addr];
    end
    assign e_ra = issue_v[VB-1:0];
endmodule

// A small RAM with a registered read (block RAM or MLAB).
module fm_ram #(
    parameter int W = 8,
    parameter int A = 5
) (
    input  logic         clk,
    input  logic         we,
    input  logic [A-1:0] wa,
    input  logic [W-1:0] wd,
    input  logic [A-1:0] ra,
    output logic [W-1:0] q
);
    logic [W-1:0] mem [1 << A];
    always_ff @(posedge clk) begin
        if (we) mem[wa] <= wd;
        q <= mem[ra];
    end
endmodule
