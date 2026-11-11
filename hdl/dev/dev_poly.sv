// D154-D157 poly sampling synthesizer (M7.7): `bin_count` bins (1-4; a 3200 has
// 1, a 6400 2, M15) of 32 voices (the last bin `last_voices`, 4-32, M16), each bin with size_units x 64K words of
// poly memory (256 units = 32 MB, 65536 sectors, a 3200's; bins x size up
// to 224 MB on the MiSTer, M10) behind a word port; bin b's memory is
// words b x size_units x 64K up. The behaviour is sim/devices/poly.py's,
// register for register and tick for tick (the evidence and the choices
// are there and in docs/poly-synth.md).
//
//   D155 write: channel (8 bits: bin 7-6, channel 5-0); read: the channel
//        if its bin is present, else 0.
//   D156 write: function code; read: it.
//   D157 write: data for (channel, FC); FC then moves to its successor.
//        read: FC 12 the voice count code, FC 22 poly memory (address++),
//        else the selected voice's register (channels 32-63 of a bin read 0).
//        Poly memory reads and writes go to the selected channel's bin.
//   D154: accepted, reads 0.
// With `enable` low (no poly bit in D51) the device answers as the old stub:
// writes accepted, reads 0, nothing changes.
//
// Time: `tick`/`tick_ns` advance simulated time. Every 9900 ns a rate pass
// steps the sounding voices (INC/MOD divider, position, end and loop); every
// 40 000 ns an envelope pass steps the envelopes and volume ramps that are
// still moving. A D157 access waits until both passes have caught up with the
// current time, as the Python model advances before each access. The passes
// read and write the voice rows in block RAM, one voice per clock.
//
// Audio: on each `mix_in_valid` (a 48 kHz FM sample) the voices' current
// words are fetched from poly memory and mixed: sample x EVAL x volume >> 24
// per side, summed, added to the FM sample, clipped to 16 bits. The fetches
// go out on the read stream port (s_*) without waiting for each other: a
// read per sounding voice, its data back in order (s_rvalid), so 64-128
// voices fit in a 48 kHz sample whatever the DDR3 latency.
//
// Multichannel distributor (M19, dev_multi.sv, sim/devices/multi.py): each
// voice side has a routing tag {connected, output} (rt_*; voice = 32 x bin
// + channel, the first 96 have inputs); with an output pair selected
// (out_pair = n: outputs 2n - 2, 2n - 1, 0-based) each read in flight
// carries where its left and right go, so the mix sums that pair instead of
// the stereo mix (mono cards: no left side). For the level detector (q_*:
// q_live) three bits per voice follow the CPU's writes: envelope limit,
// right and left destination volume non-zero.
//
// After reset the device clears its block RAM rows and all poly memory
// (E_MCLR).
//
// (Written for Quartus 17: plain constants, no enum-typed function
// arguments, no variables declared inside procedural blocks.)
module dev_poly #(
    parameter int MEM_BITS = 24                  // poly address space: 2^MEM_BITS words
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        enable,
    input  logic [2:0]  bin_count,    // bins present, 1-4 (others read as 1)
    input  logic [10:0] size_units,   // memory per bin: size_units x 65536 words (128 KB)
    input  logic [5:0]  last_voices,  // voices in the last bin, 4-32 (M16; others: 32)
    input  logic        mono,         // mono voice cards (o#pvoice): the right sum to both outputs
    input  logic        tick,
    input  logic [9:0]  tick_ns,

    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D154, 1 D155, 2 D156, 3 D157
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,

    output logic [MEM_BITS-1:0] m_addr,
    output logic        m_rd,
    output logic        m_wr,
    output logic        m_wide,       // with m_wr: the 512 words from m_addr (a multiple of 512)
    output logic        clearing,     // the memory clear after reset is running
    output logic [15:0] m_wdata,
    input  logic [15:0] m_rdata,
    input  logic        m_ack,

    // mix reads: s_rd held with s_addr until s_ack (command taken; the
    // clock after s_ack is ignored); data in order, one s_rvalid each
    output logic [MEM_BITS-1:0] s_addr,
    output logic        s_rd,
    input  logic        s_ack,
    input  logic        s_rvalid,
    input  logic [15:0] s_rdata,

    input  logic        mix_in_valid,
    input  logic signed [15:0] mix_in_l,
    input  logic signed [15:0] mix_in_r,
    output logic        mix_out_valid,
    output logic signed [15:0] mix_out_l,
    output logic signed [15:0] mix_out_r,

    input  logic [3:0]  out_pair,     // M19: 0 the stereo mix, n distributor outputs 2n-2, 2n-1
    input  logic        rt_we,        // M19: voice rt_voice's side rt_side switched to rt_tag
    input  logic [6:0]  rt_voice,
    input  logic        rt_side,
    input  logic [4:0]  rt_tag,       //   {connected, output[3:0]}
    input  logic [6:0]  q_voice,      // M19 level detector: does this voice side sound?
    input  logic        q_side,
    output logic        q_live
);
    localparam logic [47:0] RATE_NS = 48'd9900, ENV_NS = 48'd40000;
    localparam logic [6:0] FC_NUMV = 7'd12, FC_WMA = 7'd16, FC_RMA = 7'd20, FC_MDATA_W = 7'd18,
                           FC_MDATA_R = 7'd22, FC_ON = 7'd10, FC_RON = 7'd11, FC_INC = 7'd8,
                           FC_MOD = 7'd9, FC_EVSM = 7'd59;

    localparam logic [3:0] E_CLEAR = 4'd0, E_IDLE = 4'd1, E_RATE = 4'd2, E_ENV = 4'd3,
                           E_CPU_RD = 4'd4, E_MEM = 4'd6, E_MIX_RD = 4'd7,
                           E_MIX_Q = 4'd8, E_MIX_ISS = 4'd9, E_MIX_WAIT = 4'd10, E_MIX_OUT = 4'd11,
                           E_MCLR = 4'd12;

    // ------------------------------------------------------------ helpers
    function automatic logic [6:0] succ(input logic [6:0] f);
        case (f)
            7'd0: succ = 7'd1;  7'd1: succ = 7'd2;  7'd2: succ = 7'd3;  7'd3: succ = 7'd4;
            7'd4: succ = 7'd5;  7'd5: succ = 7'd6;  7'd6: succ = 7'd7;  7'd7: succ = 7'd8;
            7'd8: succ = 7'd9;  7'd9: succ = 7'd10;
            7'd16: succ = 7'd17; 7'd17: succ = 7'd18; 7'd20: succ = 7'd21; 7'd21: succ = 7'd22;
            7'd33: succ = 7'd35; 7'd35: succ = 7'd38; 7'd38: succ = 7'd32; 7'd32: succ = 7'd34;
            7'd34: succ = 7'd36; 7'd36: succ = 7'd37;
            7'd40: succ = 7'd42; 7'd42: succ = 7'd41; 7'd41: succ = 7'd43;
            7'd25: succ = 7'd0;  7'd26: succ = 7'd0;  7'd27: succ = 7'd28;
            default: succ = f;
        endcase
    endfunction

    // env/volume field index (0 ECNT 1 EMOD 2 EACU 3 EINC 4 ELIM 5 EVAL 6 EDEL
    // 7 RCUR 8 RDEST 9 LCUR 10 LDEST), 15 = not an envelope FC
    function automatic logic [3:0] env_field(input logic [6:0] f);
        case (f)
            7'd32: env_field = 4'd0;  7'd33: env_field = 4'd1;  7'd34: env_field = 4'd2;
            7'd35: env_field = 4'd3;  7'd36: env_field = 4'd4;  7'd37: env_field = 4'd5;
            7'd38: env_field = 4'd6;  7'd40: env_field = 4'd7;  7'd41: env_field = 4'd8;
            7'd42: env_field = 4'd9;  7'd43: env_field = 4'd10;
            default: env_field = 4'd15;
        endcase
    endfunction

    function automatic logic [11:0] ramp(input logic [11:0] cur, input logic [11:0] dest);
        logic [11:0] mag, st;
        mag = dest > cur ? dest - cur : cur - dest;
        st = (mag >> 9) == 12'd0 ? 12'd1 : (mag >> 9);
        if (cur == dest) ramp = cur;
        else if (dest > cur) ramp = cur + st;
        else ramp = cur - st;
    endfunction

    // ------------------------------------------------------- voice rows
    // voice v = {bin, channel[4:0]}, 128 rows (rows of absent bins unused)
    // vr: {wl[27:0], ba[27:0], ll[27:0], pi[27:0], inc_w[7:0], mod_w[7:0], pos[29:0], acc[8:0]}
    localparam int VR_W = 167;
    localparam int ER_W = 132;                   // 11 x 12-bit envelope/volume fields
    logic [VR_W-1:0] vr_mem [128];
    logic [ER_W-1:0] er_mem [128];
    logic [15:0]     wd_mem [1024];              // FC 0-7 words as written
    logic [VR_W-1:0] vr_q, vr_wd;
    logic [ER_W-1:0] er_q, er_wd;
    logic [15:0]     wd_q, wd_wd;
    logic [6:0]      vr_ra, vr_wa, er_ra, er_wa;
    logic [9:0]      wd_ra, wd_wa;
    logic            vr_we, er_we, wd_we;
    always_ff @(posedge clk) begin
        if (vr_we) vr_mem[vr_wa] <= vr_wd;
        if (er_we) er_mem[er_wa] <= er_wd;
        if (wd_we) wd_mem[wd_wa] <= wd_wd;
        vr_q <= vr_mem[vr_ra];
        er_q <= er_mem[er_ra];
        wd_q <= wd_mem[wd_ra];
    end

    wire [27:0] q_wl = vr_q[166:139], q_ba = vr_q[138:111], q_ll = vr_q[110:83], q_pi = vr_q[82:55];
    wire [7:0]  q_inc = vr_q[54:47], q_mod = vr_q[46:39];
    wire signed [29:0] q_pos = vr_q[38:9];
    wire [8:0]  q_acc = vr_q[8:0];

    // ------------------------------------------------------------ state
    logic [7:0]  channel;
    logic [6:0]  fc;
    logic [15:0] addr_hi;
    logic [27:0] addr;
    logic [127:0] on0, on1, master;
    logic [47:0] now, next_rate, next_env;
    wire rate_due = next_rate <= now;
    wire env_due  = next_env <= now;

    logic        req, req_rd;
    logic [1:0]  req_reg;
    logic [15:0] req_w;
    logic [6:0]  req_fc;
    wire  start = sel && (rd || wr) && !ack && !req;

    logic [3:0]  es;
    logic [10:0] cnt;
    logic [6:0]  pv;
    logic        pq;
    logic [3:0]  rfield;                         // CPU read/RMW: what to take from q
    logic [29:0] maddr;
    logic        mwr;

    wire [2:0] nb = bin_count >= 3'd1 && bin_count <= 3'd4 ? bin_count : 3'd1;
    wire [7:0] nv = {nb, 5'd0};                  // voices: 32 per bin
    wire [6:0] last_v = 7'(nv - 8'd1);
    wire       bin_ok = {1'b0, channel[7:6]} < nb;
    wire [5:0] lastn = last_voices >= 6'd4 && last_voices <= 6'd32 ? last_voices : 6'd32;
    // voices in the latched channel's bin (an absent bin reads as 32)
    wire [5:0] bin_nv = bin_ok && {1'b0, channel[7:6]} == nb - 3'd1 ? lastn : 6'd32;
    wire       ch_ok = !channel[5] && bin_ok && {1'b0, channel[4:0]} < bin_nv;
    // PSNUMV: voices / 4 | 0x10 | (voices > 16 ? 0x20 : 0), e.g. 32 -> 0x38
    wire [15:0] numv = {10'd0, bin_nv > 6'd16, 1'b1, bin_nv[5:2]};
    wire [6:0] cv = {channel[7:6], channel[4:0]};
    wire [3:0] req_env = env_field(req_fc);
    wire [27:0] limit    = {1'b0, size_units, 16'd0} > 28'(1) << MEM_BITS ? 28'(1) << MEM_BITS
                                                                       : {1'b0, size_units, 16'd0};
    wire       in_range = addr < limit && bin_ok;
    // bin b's memory starts at b x limit
    function automatic logic [29:0] boff(input logic [1:0] b, input logic [27:0] lim);
        case (b)
            2'd0: boff = 30'd0;
            2'd1: boff = {2'd0, lim};
            2'd2: boff = {1'b0, lim, 1'b0};
            default: boff = {2'd0, lim} + {1'b0, lim, 1'b0};
        endcase
    endfunction
    wire [29:0] total = boff(2'(nb - 3'd1), limit) + {2'd0, limit};

    // ---------------------------------------------------- rate pass step
    wire        r_slave  = pv[0] && master[pv - 7'd1];
    wire        r_active = on0[pv] && !r_slave;
    wire [9:0]  r_inc    = {2'd0, q_inc} + 10'd1;
    wire [9:0]  r_mod    = 10'd256 - {2'd0, q_mod};
    wire [9:0]  r_acc_a  = {1'b0, q_acc} + r_inc;
    wire        r_step   = r_acc_a >= r_mod;
    wire [9:0]  r_acc_n  = r_step ? r_acc_a - r_mod : r_acc_a;
    wire signed [31:0] r_pos_a = 32'(q_pos) + {4'd0, q_pi};
    wire signed [31:0] r_end   = r_pos_a + {{4{q_wl[27]}}, q_wl};
    wire signed [31:0] r_pos_l = r_pos_a + {{4{q_ll[27]}}, q_ll};
    wire        r_loop   = on1[pv] && q_ll != 28'd0;
    logic signed [31:0] r_pos_n;
    logic       r_stop;
    always_comb begin
        r_pos_n = 32'(q_pos);
        r_stop = 1'b0;
        if (r_step) begin
            r_pos_n = r_pos_a;
            if (r_end >= 0) begin
                if (r_loop) r_pos_n = r_pos_l < 0 ? 32'sd0 : r_pos_l;
                else r_stop = 1'b1;
            end
        end
    end

    // ------------------------------------------------ envelope pass step
    logic [11:0] ef [11];
    logic [11:0] ef_n [11];
    logic [12:0] e_cnt1, e_acu1;
    logic [12:0] e_up, e_dn;
    logic        e_settled;
    always_comb begin
        for (int i = 0; i < 11; i++) ef[i] = er_q[12 * i +: 12];
        for (int i = 0; i < 11; i++) ef_n[i] = ef[i];
        e_settled = ef[5] == ef[4] && ef[7] == ef[8] && ef[9] == ef[10];
        e_cnt1 = {1'b0, ef[0]} + 13'd1;
        e_acu1 = {1'b0, ef[2]} + {1'b0, ef[3]};
        e_up = {1'b0, ef[5]} + {1'b0, ef[6]};
        e_dn = {1'b0, ef[5]} - {1'b0, ef[6]};
        if (e_cnt1 >= 13'd4096) begin
            ef_n[0] = ef[1];
            if (e_acu1 >= 13'd4096) begin
                ef_n[2] = 12'(e_acu1 - 13'd4096);
                if (ef[5] < ef[4]) ef_n[5] = e_up > {1'b0, ef[4]} ? ef[4] : e_up[11:0];
                else if (ef[5] > ef[4]) ef_n[5] = (e_dn[12] || e_dn < {1'b0, ef[4]}) ? ef[4] : e_dn[11:0];
            end else ef_n[2] = e_acu1[11:0];
        end else ef_n[0] = e_cnt1[11:0];
        ef_n[7] = ramp(ef[7], ef[8]);
        ef_n[9] = ramp(ef[9], ef[10]);
    end
    logic [ER_W-1:0] e_row_n;
    always_comb for (int i = 0; i < 11; i++) e_row_n[12 * i +: 12] = ef_n[i];

    // ----------------------------------------------------------- mixing
    logic [29:0] mbp;                            // even voice's base + position
    logic        mon;
    logic signed [31:0] acc_l, acc_r;
    logic signed [15:0] fm_l, fm_r;
    logic        mix_req;
    wire  [29:0] q_bp = {2'd0, q_ba} + q_pos[29:0];
    wire         x_slave = pv[0] && master[pv - 7'd1];
    wire  [29:0] x_bp = x_slave ? mbp + 30'd1 : q_bp;      // within the bin
    wire         x_fetch = (x_slave ? mon : on0[pv]) && er_q[60 +: 12] != 12'd0
                           && x_bp < {2'd0, limit};
    // factors of each read in flight {EVAL, L cur, R cur}, in issue order;
    // the data comes back in the same order: a 3-stage multiply-accumulate
    logic [39:0] fq [128];
    logic [39:0] fq_q;
    logic [7:0]  fq_wp, fq_rp;
    wire         fq_we = es == E_MIX_Q && x_fetch;
    wire  [7:0]  fq_rp_n = s_rvalid ? fq_rp + 8'd1 : fq_rp;
    always_ff @(posedge clk) begin
        if (fq_we) fq[fq_wp[6:0]] <= {x_rb, er_q[60 +: 12], er_q[108 +: 12], er_q[84 +: 12]};
        fq_q <= fq[fq_rp_n[6:0]];
    end
    // M19: routing tags (read with the row, q at E_MIX_Q) and detector bits
    logic [4:0]  tag_l [128], tag_r [128];
    logic [4:0]  tag_q [2];
    wire         tag_clr = es == E_CLEAR && cnt < 11'd128;
    wire  [6:0]  tag_wa = tag_clr ? cnt[6:0] : rt_voice;
    wire  [4:0]  tag_wd = tag_clr ? 5'd0 : rt_tag;
    always_ff @(posedge clk) begin
        if (tag_clr || (rt_we && !rt_side)) tag_l[tag_wa] <= tag_wd;
        if (tag_clr || (rt_we && rt_side)) tag_r[tag_wa] <= tag_wd;
        tag_q[0] <= tag_l[pv];
        tag_q[1] <= tag_r[pv];
    end
    wire  [3:0]  pa = {3'(out_pair - 4'd1), 1'b0}, pb = {3'(out_pair - 4'd1), 1'b1};
    wire  [3:0]  x_rb = out_pair == 4'd0 ? 4'b1001 :
                        {tag_q[1] == {1'b1, pb}, tag_q[1] == {1'b1, pa},
                         !mono && tag_q[0] == {1'b1, pb}, !mono && tag_q[0] == {1'b1, pa}};
    logic [127:0] elim_nz, rdest_nz, ldest_nz;
    assign q_live = elim_nz[q_voice] && (q_side ? rdest_nz[q_voice] : ldest_nz[q_voice] && !mono);
    logic        a1, a2;                         // stage valid
    logic signed [15:0] x_s;
    logic [11:0] x_eval, x_lcur, x_rcur, y_lcur, y_rcur;
    logic [3:0]  x_rb_q, y_rb;                   // {rr, rl, lr, ll} of the read
    logic signed [28:0] y_e;
    wire signed [28:0] x_e = x_s * $signed({1'b0, x_eval});
    wire signed [41:0] x_pl = y_e * $signed({1'b0, y_lcur});
    wire signed [41:0] x_pr = y_e * $signed({1'b0, y_rcur});
    wire         mix_drained = fq_wp == fq_rp && !a1 && !a2;
    logic [29:0] s_addr_w;
    assign s_addr = s_addr_w[MEM_BITS-1:0];
    assign s_rd = es == E_MIX_ISS;
    wire signed [32:0] o_l = 33'(fm_l) + 33'(mono && out_pair == 4'd0 ? acc_r : acc_l);
    wire signed [32:0] o_r = 33'(fm_r) + 33'(acc_r);
    function automatic logic signed [15:0] sat(input logic signed [32:0] v);
        if (v > 33'sd32767) sat = 16'sd32767;
        else if (v < -33'sd32768) sat = -16'sd32768;
        else sat = v[15:0];
    endfunction

    // ------------------------------------------------- RAM port control
    always_comb begin
        vr_ra = cnt[6:0]; er_ra = cnt[6:0]; wd_ra = {cv, req_fc[2:0] - 3'd1};
        vr_we = 1'b0; er_we = 1'b0; wd_we = 1'b0;
        vr_wa = pv; er_wa = pv; wd_wa = {cv, req_fc[2:0]};
        vr_wd = vr_q; er_wd = e_row_n; wd_wd = req_w;
        case (es)
            E_CLEAR: begin
                wd_we = 1'b1; wd_wa = cnt[9:0]; wd_wd = 16'd0;
                vr_we = cnt[2:0] == 3'd0; vr_wa = cnt[9:3];
                vr_wd = {112'd0, 8'd255, 8'd0, 30'd0, 9'd0};
                er_we = cnt[2:0] == 3'd0; er_wa = cnt[9:3]; er_wd = '0;
            end
            E_RATE: if (pq && r_active) begin
                vr_we = 1'b1;
                vr_wd = {vr_q[166:39], r_pos_n[29:0], r_acc_n[8:0]};
            end
            E_ENV: if (pq && !e_settled) er_we = 1'b1;
            E_IDLE: begin
                vr_ra = cv; er_ra = cv;
                wd_ra = req_rd ? {cv, req_fc[2:0]} : {cv, req_fc[2:0] - 3'd1};
                // FC 0-7 writes go straight into the word RAM when accepted
                if (req && enable && !req_rd && req_reg == 2'd3 && !rate_due && !env_due
                        && ch_ok && req_fc < 7'd8)
                    wd_we = 1'b1;
            end
            E_CPU_RD: begin                      // q holds the row; writes modify it
                vr_ra = cv; er_ra = cv;
                vr_wa = cv; er_wa = cv;
                if (!req_rd) case (rfield)
                    4'd1: begin vr_we = 1'b1;            // two-word value (req_fc odd)
                        case (req_fc[2:1])
                            2'd0: vr_wd = {req_w[11:8], wd_q, req_w[7:0], vr_q[138:0]};
                            2'd1: vr_wd = {vr_q[166:139], req_w[11:8], wd_q, req_w[7:0], vr_q[110:0]};
                            2'd2: vr_wd = {vr_q[166:111], req_w[11:8], wd_q, req_w[7:0], vr_q[82:0]};
                            default: vr_wd = {vr_q[166:83], req_w[11:8], wd_q, req_w[7:0], vr_q[54:0]};
                        endcase
                    end
                    4'd2: begin vr_we = 1'b1; vr_wd = {vr_q[166:55], req_w[7:0], vr_q[46:0]}; end
                    4'd3: begin vr_we = 1'b1; vr_wd = {vr_q[166:47], req_w[7:0], vr_q[38:0]}; end
                    4'd4: begin vr_we = 1'b1; vr_wd = {vr_q[166:39], 30'd0, 9'd0}; end
                    4'd5: begin er_we = 1'b1; er_wd = er_q;
                        er_wd[12 * req_env +: 12] = req_w[11:0];
                    end
                    default: ;
                endcase
            end
            E_MIX_RD: begin vr_ra = pv; er_ra = pv; end
            default: ;
        endcase
    end

    assign m_addr  = maddr[MEM_BITS-1:0];
    assign m_rd    = es == E_MEM && !mwr;
    assign m_wr    = (es == E_MEM && mwr) || es == E_MCLR;
    assign m_wdata = es == E_MCLR ? 16'd0 : req_w;
    assign m_wide  = es == E_MCLR;
    assign clearing = es == E_CLEAR || es == E_MCLR;

    // ------------------------------------------------------------ engine
    always_ff @(posedge clk) begin
        ack <= 1'b0;
        mix_out_valid <= 1'b0;
        if (tick && !rst) now <= now + {38'd0, tick_ns};
        // mix reads coming back: factors, then sample x EVAL, then x volume
        a1 <= s_rvalid;
        if (s_rvalid) begin
            x_s <= s_rdata;
            {x_rb_q, x_eval, x_lcur, x_rcur} <= fq_q;
            fq_rp <= fq_rp_n;
        end
        a2 <= a1;
        if (a1) begin y_e <= x_e; y_lcur <= x_lcur; y_rcur <= x_rcur; y_rb <= x_rb_q; end
        if (a2) begin
            acc_l <= acc_l + (y_rb[0] ? 32'(x_pl >>> 24) : 32'sd0) + (y_rb[2] ? 32'(x_pr >>> 24) : 32'sd0);
            acc_r <= acc_r + (y_rb[1] ? 32'(x_pl >>> 24) : 32'sd0) + (y_rb[3] ? 32'(x_pr >>> 24) : 32'sd0);
        end
        if (mix_in_valid) begin
            fm_l <= mix_in_l; fm_r <= mix_in_r;
            mix_req <= 1'b1;
        end
        if (start) begin
            req <= 1'b1; req_rd <= rd; req_reg <= reg_sel; req_w <= wdata; req_fc <= fc;
        end
        if (rst) begin
            es <= E_CLEAR; cnt <= '0;
            channel <= '0; fc <= '0; addr_hi <= '0; addr <= '0;
            on0 <= '0; on1 <= '0; master <= '0;
            elim_nz <= '0; rdest_nz <= '0; ldest_nz <= '0;
            now <= '0; next_rate <= '0; next_env <= '0;
            req <= 1'b0; mix_req <= 1'b0; pq <= 1'b0;
            fq_wp <= '0; fq_rp <= '0; a1 <= 1'b0; a2 <= 1'b0;
        end else case (es)
            E_CLEAR: begin
                cnt <= cnt + 11'd1;
                if (cnt == 11'd1023) begin
                    es <= E_MCLR; cnt <= '0; maddr <= '0; req_w <= 16'd0;
                end
            end
            // all poly memory to zero, as the model starts: SYN-5.3 reads
            // some of it before writing (the bin header, the size probe's
            // saved words, sectors 22-25 at start-up), and DDR3 holds
            // whatever was there before. bins x limit / 512 wide writes,
            // each a 128-beat DDR3 burst; poly accesses wait for it.
            E_MCLR: if (m_ack) begin
                maddr <= maddr + 30'd512;
                if (maddr + 30'd512 >= total) es <= E_IDLE;
            end
            E_IDLE:
                if (rate_due) begin
                    es <= E_RATE; cnt <= '0; pq <= 1'b0;
                end else if (env_due) begin
                    es <= E_ENV; cnt <= '0; pq <= 1'b0;
                end else if (req && !enable) begin       // the old stub
                    rdata <= 16'd0; ack <= 1'b1; req <= 1'b0;
                end else if (req && req_reg != 2'd3) begin
                    rdata <= 16'd0;
                    if (req_reg == 2'd1) begin
                        if (!req_rd) channel <= req_w[7:0];
                        else rdata <= bin_ok ? {8'd0, channel} : 16'd0;
                    end else if (req_reg == 2'd2) begin
                        if (!req_rd) fc <= req_w[6:0];
                        else rdata <= {9'd0, fc};
                    end
                    ack <= 1'b1; req <= 1'b0;
                end else if (req && req_rd) begin   // D157 read
                    rdata <= 16'd0;
                    if (req_fc == FC_NUMV) begin
                        rdata <= numv; ack <= 1'b1; req <= 1'b0;
                    end else if (req_fc == FC_MDATA_R) begin
                        addr <= addr + 28'd1;
                        if (in_range) begin maddr <= boff(channel[7:6], limit) + {2'd0, addr}; mwr <= 1'b0; es <= E_MEM; end
                        else begin ack <= 1'b1; req <= 1'b0; end
                    end else if (!ch_ok) begin
                        ack <= 1'b1; req <= 1'b0;
                    end else if (req_fc == FC_ON || req_fc == FC_RON) begin
                        rdata <= {14'd0, on1[cv], on0[cv]}; ack <= 1'b1; req <= 1'b0;
                    end else if (req_fc < 7'd8) begin
                        rfield <= 4'd0; es <= E_CPU_RD;
                    end else if (req_fc == FC_INC || req_fc == FC_MOD) begin
                        rfield <= req_fc == FC_INC ? 4'd2 : 4'd3; es <= E_CPU_RD;
                    end else if (req_env != 4'd15) begin
                        rfield <= 4'd5; es <= E_CPU_RD;
                    end else begin
                        ack <= 1'b1; req <= 1'b0;
                    end
                end else if (req) begin              // D157 write
                    fc <= succ(req_fc);
                    if (req_fc == FC_WMA || req_fc == FC_RMA) begin
                        addr_hi <= req_w; ack <= 1'b1; req <= 1'b0;
                    end else if (req_fc == FC_WMA + 7'd1 || req_fc == FC_RMA + 7'd1) begin
                        addr <= {req_w[11:8], addr_hi, req_w[7:0]}; ack <= 1'b1; req <= 1'b0;
                    end else if (req_fc == FC_MDATA_W) begin
                        addr <= addr + 28'd1;
                        if (in_range) begin maddr <= boff(channel[7:6], limit) + {2'd0, addr}; mwr <= 1'b1; es <= E_MEM; end
                        else begin ack <= 1'b1; req <= 1'b0; end
                    end else if (!ch_ok) begin
                        ack <= 1'b1; req <= 1'b0;
                    end else if (req_fc < 7'd8) begin
                        if (req_fc[0]) begin rfield <= 4'd1; es <= E_CPU_RD; end
                        else begin ack <= 1'b1; req <= 1'b0; end
                    end else if (req_fc == FC_INC || req_fc == FC_MOD) begin
                        rfield <= req_fc == FC_INC ? 4'd2 : 4'd3; es <= E_CPU_RD;
                    end else if (req_fc == FC_ON) begin
                        on0[cv] <= req_w[0]; on1[cv] <= req_w[1];
                        if (req_w[0] && !on0[cv]) begin rfield <= 4'd4; es <= E_CPU_RD; end
                        else begin ack <= 1'b1; req <= 1'b0; end
                    end else if (req_env != 4'd15) begin
                        rfield <= 4'd5; es <= E_CPU_RD;
                    end else begin
                        if (req_fc == FC_EVSM) master[cv] <= req_w[0];
                        ack <= 1'b1; req <= 1'b0;
                    end
                end else if (mix_req) begin
                    mix_req <= 1'b0; pv <= 7'd0; acc_l <= '0; acc_r <= '0;
                    es <= E_MIX_RD;
                end
            // pipelined passes: read voice cnt, write voice pv (= cnt - 1)
            E_RATE, E_ENV: begin
                pv <= cnt[6:0];
                pq <= cnt < {3'd0, nv};
                if (es == E_RATE && pq && r_active && r_stop) on0[pv] <= 1'b0;
                cnt <= cnt + 11'd1;
                if (cnt == {3'd0, nv}) begin
                    if (es == E_RATE) next_rate <= next_rate + RATE_NS;
                    else next_env <= next_env + ENV_NS;
                    es <= E_IDLE;
                end
            end
            E_CPU_RD:                                // the row/word is in q now
                if (req_rd) begin
                    case (rfield)
                        4'd0: rdata <= wd_q;
                        4'd2: rdata <= {8'd0, q_inc};
                        4'd3: rdata <= {8'd0, q_mod};
                        default: rdata <= {4'd0, er_q[12 * req_env +: 12]};
                    endcase
                    ack <= 1'b1; req <= 1'b0; es <= E_IDLE;
                end else begin
                    if (rfield == 4'd5 && req_env == 4'd4) elim_nz[cv] <= req_w[11:0] != 12'd0;
                    if (rfield == 4'd5 && req_env == 4'd8) rdest_nz[cv] <= req_w[11:0] != 12'd0;
                    if (rfield == 4'd5 && req_env == 4'd10) ldest_nz[cv] <= req_w[11:0] != 12'd0;
                    ack <= 1'b1; req <= 1'b0; es <= E_IDLE;
                end
            E_MEM: if (m_ack) begin
                rdata <= mwr ? 16'd0 : m_rdata;
                ack <= 1'b1; req <= 1'b0; es <= E_IDLE;
            end
            // the mix: read each voice's row, issue a read for each one that
            // sounds; the reads come back above; then wait for the last
            E_MIX_RD: es <= E_MIX_Q;
            E_MIX_Q: begin
                if (!pv[0]) begin mbp <= q_bp; mon <= on0[pv]; end
                if (x_fetch) begin
                    s_addr_w <= boff(pv[6:5], limit) + x_bp;
                    fq_wp <= fq_wp + 8'd1;
                    es <= E_MIX_ISS;
                end else if (pv == last_v) es <= E_MIX_WAIT;
                else begin pv <= pv + 7'd1; es <= E_MIX_RD; end
            end
            E_MIX_ISS: if (s_ack) begin
                if (pv == last_v) es <= E_MIX_WAIT;
                else begin pv <= pv + 7'd1; es <= E_MIX_RD; end
            end
            E_MIX_WAIT: if (mix_drained) es <= E_MIX_OUT;
            E_MIX_OUT: begin
                mix_out_l <= sat(o_l); mix_out_r <= sat(o_r);
                mix_out_valid <= 1'b1;
                es <= E_IDLE;
            end
            default: es <= E_IDLE;
        endcase
    end
endmodule
