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
    logic          vb_ok, ve_ok, vf_ok, vg_ok, vh_ok;
    logic [VB-1:0] vb_a;
    // Stages C (L0) .. D (L7): per lane (bank 0 = modulator, 1 = carrier)
    // the oscillator's accumulator mod divisor (3 x 3 bits), then
    // (acc + n x increment) / divisor (3 + 4 + 4 + 4 bits); the interpolator's
    // (prescale + clocks due) / (256 - divisor) (3 x 3 bits), then its
    // multiply and clamp (L4). Restoring division, at most 4 bits a clock
    // (a 50 MHz clock). None due: the interpolator is unchanged, as
    // advance_to returns early.
    typedef struct packed {
        logic [8:0]  dv;      // oscillator divisor
        logic [14:0] m;       // n x increment
        logic [8:0]  acc;     // accumulator: the modulo's dividend
        logic [8:0]  r;       // running remainder
        logic [14:0] sum;     // the quotient's dividend
        logic [14:0] q;       // quotient so far
        logic [2:0]  sh;
        logic [7:0]  opre, opt;
        logic        inone;   // no interpolator clock due
        logic [8:0]  itot, idd, ir, iq, iopre, iacc, ival;
        logic [7:0]  iadd, ilim;
    } lane_t;
    localparam int NL = 8;
    lane_t         L [NL][2];
    logic [NL-1:0] lok;
    logic [VB-1:0] la [NL];
    logic [7:0]    lf13m [NL], lf13k [NL], ltimk [NL];

    // nb (<= 4) bits of restoring division: `bits` (MSB first) into
    // remainder r by dvs; returns {quotient bits, remainder}
    function automatic logic [12:0] dstep(input logic [8:0] r, input logic [3:0] bits,
                                          input int nb, input logic [8:0] dvs);
        logic [9:0] x;
        logic [3:0] q;
        x = {1'b0, r}; q = '0;
        for (int i = 3; i >= 0; i--)
            if (i < nb) begin
                x = {x[8:0], bits[i]};
                if (x >= {1'b0, dvs}) begin x = x - {1'b0, dvs}; q[i] = 1'b1; end
            end
        dstep = {q, x[8:0]};
    endfunction

    // the interpolator's multiply and clamp, from L3
    function automatic lane_t interp_mul(input lane_t l);
        logic [16:0] sum;
        logic [9:0]  steps;
        logic [7:0]  val, lim;
        interp_mul = l;
        if (!l.inone) begin
            sum   = {9'd0, l.iacc[7:0]} + 17'(l.iq) * (17'(l.iadd) + 17'd1);
            steps = {1'b0, sum[16:8]};
            val   = l.ival[7:0];
            lim   = l.ilim;
            interp_mul.iopre = l.ir;
            interp_mul.iacc  = l.iq == 9'd0 ? l.iacc : {1'b0, sum[7:0]};
            if (val < lim)
                interp_mul.ival = 10'(val) + steps >= 10'(lim) ? 9'(lim) : 9'(val + steps[7:0]);
            else if (val > lim)
                interp_mul.ival = 10'(lim) + steps >= 10'(val) ? 9'(lim) : 9'(val - steps[7:0]);
        end
    endfunction

    // stage D (L7)
    wire           vd_ok = lok[NL-1];
    wire [VB-1:0]  vd_a  = la[NL-1];
    logic [14:0]   d_pulses [2];
    logic [8:0]    d_acc [2];
    logic [2:0]    d_sh [2];
    logic [7:0]    d_opre [2], d_opt [2];
    logic [8:0]    d_keep [2][3];                // value, interp prescale, interp acc
    always_comb
        for (int b = 0; b < 2; b++) begin
            d_pulses[b] = L[NL-1][b].q; d_acc[b] = L[NL-1][b].r; d_sh[b] = L[NL-1][b].sh;
            d_opre[b] = L[NL-1][b].opre; d_opt[b] = L[NL-1][b].opt;
            d_keep[b][0] = L[NL-1][b].ival; d_keep[b][1] = L[NL-1][b].iopre; d_keep[b][2] = L[NL-1][b].iacc;
        end
    wire [7:0] d_vm = L[NL-1][0].ival[7:0], d_vk = L[NL-1][1].ival[7:0];
    wire [7:0] d_f13m = lf13m[NL-1], d_f13k = lf13k[NL-1], d_timk = ltimk[NL-1];

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
            vb_ok <= 1'b0; lok <= '0; ve_ok <= 1'b0;
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
                end else if (!vb_ok && lok == '0 && !ve_ok && !vf_ok && !vg_ok && !vh_ok) begin
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

            // ---- B -> L0: operands
            lok[0] <= vb_ok; la[0] <= vb_a;
            for (int b = 0; b < 2; b++) begin
                automatic logic [5:0] n = base - s_q[b][6][5:0];
                L[0][b].dv   <= 9'd256 - 9'(p_q[b][1]) + 9'(p_q[b][0][7:3]);
                L[0][b].m    <= 15'(n) * (15'(p_q[b][0]) + 15'd1);
                L[0][b].acc  <= s_q[b][5];
                L[0][b].r    <= '0;
                L[0][b].sum  <= '0;
                L[0][b].q    <= '0;
                L[0][b].sh   <= 3'd7 - p_q[b][2][2:0];
                L[0][b].opre <= s_q[b][4][7:0];
                L[0][b].opt  <= s_q[b][3][7:0];
                L[0][b].inone <= 2'(ibase - s_q[b][7][1:0]) == 2'd0;
                L[0][b].itot <= {1'b0, s_q[b][1][7:0]} + 9'(2'(ibase - s_q[b][7][1:0]));
                L[0][b].idd  <= 9'd256 - {1'b0, p_q[b][5]};
                L[0][b].ir   <= '0;
                L[0][b].iq   <= '0;
                L[0][b].iopre <= s_q[b][1];
                L[0][b].iacc <= s_q[b][2];
                L[0][b].ival <= s_q[b][0];
                L[0][b].iadd <= p_q[b][6];
                L[0][b].ilim <= p_q[b][7];
            end
            lf13m[0] <= p_q[0][4]; lf13k[0] <= p_q[1][4]; ltimk[0] <= p_q[1][3];

            // ---- L0 .. L7
            for (int k = 1; k < NL; k++) begin
                lok[k] <= lok[k-1]; la[k] <= la[k-1];
                lf13m[k] <= lf13m[k-1]; lf13k[k] <= lf13k[k-1]; ltimk[k] <= ltimk[k-1];
            end
            for (int b = 0; b < 2; b++) begin
                automatic lane_t l0 = L[0][b], l1 = L[1][b], l2 = L[2][b], l3 = L[3][b];
                automatic lane_t l4 = L[4][b], l5 = L[5][b], l6 = L[6][b];
                automatic logic [12:0] o, i;
                automatic logic [14:0] sm;
                // L1-L3: acc mod dv, 3 bits each; the interpolator's divide likewise
                o = dstep(l0.r, {1'b0, l0.acc[8:6]}, 3, l0.dv);  i = dstep(l0.ir, {1'b0, l0.itot[8:6]}, 3, l0.idd);
                l0.r = o[8:0]; l0.ir = i[8:0]; l0.iq[8:6] = i[11:9];
                L[1][b] <= l0;
                o = dstep(l1.r, {1'b0, l1.acc[5:3]}, 3, l1.dv);  i = dstep(l1.ir, {1'b0, l1.itot[5:3]}, 3, l1.idd);
                l1.r = o[8:0]; l1.ir = i[8:0]; l1.iq[5:3] = i[11:9];
                L[2][b] <= l1;
                o = dstep(l2.r, {1'b0, l2.acc[2:0]}, 3, l2.dv);  i = dstep(l2.ir, {1'b0, l2.itot[2:0]}, 3, l2.idd);
                l2.r = o[8:0]; l2.ir = i[8:0]; l2.iq[2:0] = i[11:9];
                L[3][b] <= l2;
                // L4: the quotient's dividend and its bits 14-12; the interpolator's multiply
                sm = 15'(l3.r) + l3.m;
                o = dstep(9'd0, {1'b0, sm[14:12]}, 3, l3.dv);
                l3 = interp_mul(l3);
                l3.sum = sm; l3.r = o[8:0]; l3.q[14:12] = o[11:9];
                L[4][b] <= l3;
                // L5-L7: quotient bits 11-8, 7-4, 3-0 (the remainder is the new accumulator)
                o = dstep(l4.r, l4.sum[11:8], 4, l4.dv);  l4.r = o[8:0]; l4.q[11:8] = o[12:9];
                L[5][b] <= l4;
                o = dstep(l5.r, l5.sum[7:4], 4, l5.dv);   l5.r = o[8:0]; l5.q[7:4] = o[12:9];
                L[6][b] <= l5;
                o = dstep(l6.r, l6.sum[3:0], 4, l6.dv);   l6.r = o[8:0]; l6.q[3:0] = o[12:9];
                L[7][b] <= l6;
            end

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
