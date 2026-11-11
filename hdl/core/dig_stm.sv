// Digital sample-to-memory (M18): the Synclavier3 interpreter's native
// routines 64-76 (-XPL/INTRPRTR "Digital STM interface") with an audio file
// on SD drive 5 (S5, tools/stm_source.py) as the digital input. The
// behaviour is sim/devices/digstm.py's, routine for routine (the evidence and
// the choices are there and in docs/devices/digital-stm.md).
//
// The CPU (able_cpu.sv) holds `PCI TO RTNV` + n, n = 64-76, in EXEC with
// nat_req while this handler works; no simulated time passes. Results go to
// R0 with nat_ack + nat_wr (routines without a result leave R0).
//
//   64 start        frames arrive from now: each CPU tick adds tick_ns x rate
//                   to an accumulator, one frame per 10 000 000 (rate in
//                   100 Hz units); the source starts again at frame 0
//   65 samples      frames arrived - frames taken, 0..32767
//   66 underflowed  an import or toss found fewer than 256 frames
//   67 stop         frames stop arriving
//   68 do_import    256 frames as D157 writes (dev_poly's register port,
//                   the CPU's own write path: SYN-5.3 has set the write
//                   address): 256 words mono, 512 stereo (left, right)
//   69/70 lmax/rmax max |sample| per channel of the last import or toss
//   71 toss_data    as 68 without the writes
//   72 latch(0, stereo, rate)  R0 = 1 without a valid source, else 0
//   73 release      74 get_rate   75 set_rate(rate)   76 get_chan (0)
//
// Source file: block 0 a header (big-endian words 0-3 "SYNCSTM1", 4 version
// 1, 5 channels 1/2, 6 rate in 100 Hz units, 7-8 frames), then the samples
// as big-endian words from block 1, interleaved when stereo. A stereo source
// recorded mono gives its left channel; a mono source recorded stereo the
// same word twice; frames past the end are 0. The header is read at the
// first call after reset or after S5 is mounted (the CPU is held anyway).
//
// (Written for Quartus 17: plain constants, no variables declared inside
// procedural blocks.)
module dig_stm (
    input  logic        clk,
    input  logic        rst,            // the CPU's reset
    input  logic        tick,           // CPU simulated time
    input  logic [9:0]  tick_ns,
    input  logic        src_mounted,    // S5 (re)mounted: read the header again
    input  logic        src_present,

    input  logic        nat_req,
    input  logic [3:0]  nat_num,        // routine - 64
    input  logic [15:0] r0,
    input  logic [15:0] r1,
    input  logic [15:0] r2,
    output logic        nat_ack,
    output logic        nat_wr,
    output logic [15:0] nat_result,

    // source words on SD drive 5 (sd_floppy word port): {block, word};
    // s_rd held until s_ack (one clock), data with the ack
    output logic [23:0] s_addr,
    output logic        s_rd,
    input  logic [15:0] s_rdata,
    input  logic        s_ack,

    // D157 writes into dev_poly's register port; p_wr held until p_ack (one clock)
    output logic        p_wr,
    output logic [15:0] p_wdata,
    input  logic        p_ack
);
    localparam logic [3:0] N_START = 4'd0, N_SAMPLES = 4'd1, N_UNDER = 4'd2, N_STOP = 4'd3,
                           N_IMPORT = 4'd4, N_LMAX = 4'd5, N_RMAX = 4'd6, N_TOSS = 4'd7,
                           N_LATCH = 4'd8, N_RELEASE = 4'd9, N_GET_RATE = 4'd10,
                           N_SET_RATE = 4'd11, N_GET_CHAN = 4'd12;
    localparam logic [2:0] H_IDLE = 3'd0, H_HDR = 3'd1, H_CALL = 3'd2, H_WORD = 3'd3,
                           H_RD = 3'd4, H_PUT = 3'd5, H_WR = 3'd6, H_DONE = 3'd7;
    localparam logic [23:0] FRAME_UNIT = 24'd10_000_000;

    logic [2:0]  h;
    logic        waiting;               // answered: wait for nat_req to drop
    logic        hdr_stale;
    logic [3:0]  hw;                    // header word
    logic        src_ok, src_st;
    logic [31:0] src_frames;
    logic [15:0] hdr [9];
    logic [9:0]  rate;
    logic        rec_st, running, underflow;
    logic [23:0] acc;
    logic [31:0] arrived, consumed;
    logic [15:0] lmax, rmax, lacc, racc, w;
    logic [9:0]  j;                     // word of the block
    logic        do_write;

    wire  [31:0] avail = arrived - consumed;
    wire  [8:0]  fi = rec_st ? j[9:1] : j[8:0];
    wire         ch  = rec_st & j[0];
    wire  [31:0] frame = consumed + {23'd0, fi};
    wire  [32:0] widx = src_st ? {frame, ch} : {1'b0, frame};
    wire  [15:0] blk = widx[23:8] + 16'd1;
    wire         in_src = src_ok && frame < src_frames;
    wire  [15:0] w_abs = w[15] ? 16'd0 - w : w;
    wire  [9:0]  last_j = rec_st ? 10'd511 : 10'd255;
    wire  [19:0] tick_add = tick_ns * rate;
    wire  [23:0] acc_n = acc + {4'd0, tick_add};
    wire         r0_rate_ok = r0 != 16'd0 && r0[15:10] == 6'd0;
    wire         r2_rate_ok = r2 != 16'd0 && r2[15:10] == 6'd0;
    wire         hdr_ok = hdr[0] == 16'h5359 && hdr[1] == 16'h4E43 && hdr[2] == 16'h5354 &&
                          hdr[3] == 16'h4D31 && hdr[4] == 16'd1 &&
                          (hdr[5] == 16'd1 || hdr[5] == 16'd2) &&
                          hdr[6] != 16'd0 && hdr[6][15:10] == 6'd0;

    assign s_addr = h == H_HDR ? {16'd0, 4'd0, hw} : {blk, widx[7:0]};
    assign s_rd   = h == H_HDR || h == H_RD;
    assign p_wr   = h == H_WR;
    assign p_wdata = w;

    always_ff @(posedge clk) begin
        nat_ack <= 1'b0;
        if (rst) begin
            h <= H_IDLE;
            waiting <= 1'b0;
            hdr_stale <= 1'b1;
            src_ok <= 1'b0;
            src_st <= 1'b0;
            src_frames <= '0;
            rate <= 10'd480;
            rec_st <= 1'b0; running <= 1'b0; underflow <= 1'b0;
            acc <= '0; arrived <= '0; consumed <= '0;
            lmax <= '0; rmax <= '0;
            nat_wr <= 1'b0;
        end else begin
            if (src_mounted) hdr_stale <= 1'b1;
            // frames arriving (the CPU is never held in a call while it ticks)
            if (running && tick) begin
                if (acc_n >= FRAME_UNIT) begin
                    acc <= acc_n - FRAME_UNIT;
                    arrived <= arrived + 32'd1;
                end else acc <= acc_n;
            end

            case (h)
            H_IDLE:
                if (waiting) begin
                    if (!nat_req) waiting <= 1'b0;
                end else if (nat_req) begin
                    hw <= 4'd0;
                    if (hdr_stale && src_present) h <= H_HDR;
                    else begin
                        if (hdr_stale) src_ok <= 1'b0;
                        hdr_stale <= 1'b0;
                        h <= H_CALL;
                    end
                end

            H_HDR: if (s_ack) begin                     // header words 0-8
                hdr[hw] <= s_rdata;
                hw <= hw + 4'd1;
                if (hw == 4'd8) begin
                    hdr_stale <= 1'b0;
                    h <= H_CALL;
                end
            end

            H_CALL: begin
                if (hw == 4'd9) begin                   // a header was just read
                    hw <= 4'd0;
                    src_ok <= hdr_ok;
                    if (hdr_ok) begin
                        src_st <= hdr[5] == 16'd2;
                        rate <= hdr[6][9:0];
                        src_frames <= {hdr[7], hdr[8]};
                    end
                end else begin
                    nat_wr <= 1'b0;
                    nat_result <= 16'd0;
                    h <= H_DONE;
                    case (nat_num)
                    N_START: begin
                        running <= 1'b1;
                        acc <= '0; arrived <= '0; consumed <= '0;
                        underflow <= 1'b0;
                    end
                    N_SAMPLES: begin
                        nat_wr <= 1'b1;
                        nat_result <= avail[31] ? 16'd0 : avail[30:15] != 16'd0 ? 16'h7FFF
                                                       : avail[15:0];
                    end
                    N_UNDER: begin nat_wr <= 1'b1; nat_result <= {15'd0, underflow}; end
                    N_STOP: running <= 1'b0;
                    N_IMPORT, N_TOSS: begin
                        if (avail[31] || avail[30:8] == 23'd0) underflow <= 1'b1;
                        do_write <= nat_num == N_IMPORT;
                        j <= 10'd0;
                        lacc <= 16'd0; racc <= 16'd0;
                        h <= H_WORD;
                    end
                    N_LMAX: begin nat_wr <= 1'b1; nat_result <= lmax; end
                    N_RMAX: begin nat_wr <= 1'b1; nat_result <= rmax; end
                    N_LATCH: begin
                        nat_wr <= 1'b1;
                        if (!src_ok) nat_result <= 16'd1;
                        else begin
                            rec_st <= r1[0];
                            if (r2_rate_ok) rate <= r2[9:0];
                        end
                    end
                    N_RELEASE: running <= 1'b0;
                    N_GET_RATE: begin nat_wr <= 1'b1; nat_result <= {6'd0, rate}; end
                    N_SET_RATE: if (r0_rate_ok) rate <= r0[9:0];
                    N_GET_CHAN: nat_wr <= 1'b1;
                    default: ;
                    endcase
                end
            end

            H_WORD:                                     // the source word, or 0
                if (in_src) h <= H_RD;
                else begin
                    w <= 16'd0;
                    h <= H_PUT;
                end

            H_RD: if (s_ack) begin
                w <= s_rdata;
                h <= H_PUT;
            end

            H_PUT: begin
                if (ch) begin if (w_abs > racc) racc <= w_abs; end
                else if (w_abs > lacc) lacc <= w_abs;
                if (do_write) h <= H_WR;
                else if (j == last_j) h <= H_DONE;
                else begin j <= j + 10'd1; h <= H_WORD; end
            end

            H_WR: if (p_ack) begin
                if (j == last_j) h <= H_DONE;
                else begin j <= j + 10'd1; h <= H_WORD; end
            end

            H_DONE: begin
                if (nat_num == N_IMPORT || nat_num == N_TOSS) begin
                    lmax <= lacc; rmax <= racc;
                    consumed <= consumed + 32'd256;
                end
                nat_ack <= 1'b1;
                waiting <= 1'b1;
                h <= H_IDLE;
            end

            default: h <= H_IDLE;
            endcase
        end
    end
endmodule
