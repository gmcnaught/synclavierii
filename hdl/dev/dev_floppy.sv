// D100-D104 floppy disk controller (sim/devices/floppy.py), FD1771-style.
//   D100 write command / read status; D101 track; D102 sector;
//   D103 data (seek target; sector bytes, low byte of each word first);
//   D104 write drive select (bit 0 drive, bit 1 side); D104 read: no SYN.
// Commands: Type I restore/seek/step (busy for the stepping time), Type II
// single-sector read (2xx) / write (24x) after a 50 us start, force
// interrupt (Dx). Anything else: no SYN, as in Python ("not modelled").
// Timing is the CPU's simulated time (tick/tick_ns), the index pulse from
// a 360 rpm revolution phase.
//
// The two floppies' words are in an external RAM (fd_* port; word
// address = drive, logical sector, word). Copying a sector between it and
// the 512-byte buffer takes clocks; floppy accesses wait meanwhile, at no
// simulated time, so the program sees what Python's instant copy gives.
(* multstyle = "logic" *)       // small multiplies: keep the DSP blocks for sys/
module dev_floppy (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [2:0]  reg_sel,      // 0-4: D100-D104
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        nosyn,
    input  logic        tick,
    input  logic [9:0]  tick_ns,

    // media: per drive present, protected, size and geometry
    input  logic [1:0]  present,
    input  logic [1:0]  protect,
    input  logic [10:0] sectors0,
    input  logic [10:0] sectors1,
    input  logic [3:0]  spt0,
    input  logic [3:0]  spt1,
    input  logic [1:0]  sides0,
    input  logic [1:0]  sides1,

    output logic [18:0] fd_addr,      // {drive, logical sector[9:0], word[7:0]}
    output logic        fd_rd,
    output logic        fd_wr,
    output logic [15:0] fd_wdata,
    input  logic [15:0] fd_rdata,
    input  logic        fd_ack,

    input  logic        ld_we,        // state load (simulation), see sim/lockstep.py
    input  logic [4:0]  ld_addr,
    input  logic [31:0] ld_data
);
    localparam logic [7:0] BUSY = 8'o001, DRQ = 8'o002, INDEX = 8'o002, TRACK0 = 8'o004,
                           RNF = 8'o020, HEAD_LOADED = 8'o040, PROTECT = 8'o100,
                           NOT_READY = 8'o200;
    localparam int REV_NS = 166_666_667, INDEX_NS = 4_000_000, SECTOR_START_NS = 50_000;

    logic [15:0] select;
    logic [7:0]  track, sector, data, status;
    logic        type1, kind_write, step_out;
    logic [31:0] phase;                       // time mod REV_NS
    logic signed [31:0] busy_ns, pend_wait;
    logic        pend, pend_write, pend_none; // Type II waiting to start
    logic [9:0]  pend_lsn;
    logic        buf_valid;
    logic [9:0]  pos, lsn_w;
    logic [15:0] head0, head1;
    // the sector buffer: 256 words, byte 2k = word k bits 7:0 (the first byte
    // on the disk is the low half), one write port with byte enables and a
    // registered read port (one M10K). The read port follows the D103
    // position, or the word being written back while flushing; q_word says
    // which word q holds.
    logic [7:0]  sbuf_hi [256], sbuf_lo [256];   // two plain byte RAMs (block RAM)
    logic [15:0] q;
    logic [7:0]  q_word;
    logic        b_we;
    logic [1:0]  b_be;
    logic [7:0]  b_wa;
    logic [15:0] b_wd;

    // sector copy between the media RAM and the buffer
    logic        filling, flushing;
    logic [8:0]  idx;
    logic [9:0]  copy_lsn;
    wire         copying = filling || flushing;

    wire        drive = select[0];
    wire        side  = select[1];
    wire [15:0] head  = drive ? head1 : head0;
    wire        have  = present[drive];
    wire        prot  = protect[drive];
    wire [10:0] nsec  = drive ? sectors1 : sectors0;
    wire [3:0]  spt   = drive ? spt1 : spt0;
    wire [1:0]  sides = drive ? sides1 : sides0;

    // ---------------------------------------------------------------- status
    logic [7:0] stat;
    always_comb begin
        stat = status | (have ? 8'd0 : NOT_READY);
        if (type1) begin
            stat = stat & ~(INDEX | TRACK0 | PROTECT);
            if (have) begin
                if (phase < INDEX_NS) stat = stat | INDEX;
                if (prot) stat = stat | PROTECT;
            end
            if (head == 16'd0) stat = stat | TRACK0;
        end else begin
            stat = stat & ~DRQ;
            if (buf_valid && !pend) stat = stat | DRQ;
        end
    end

    // ------------------------------------------------------- register access
    wire data_out = buf_valid && !pend && !kind_write;      // D103 read takes a byte
    wire data_in  = buf_valid && !pend && kind_write;       // D103 write stores one
    wire [3:0] hi = wdata[7:4];
    wire cmd_ok = hi == 4'o15 || status[0] || hi < 4'd8 ||
                  ((hi == 4'd8 || hi == 4'd10) && !wdata[4]);
    assign nosyn = sel && ((rd && reg_sel == 3'd4) || (wr && reg_sel == 3'd0 && !cmd_ok));
    assign ack   = sel && !nosyn && !copying;
    always_comb begin
        case (reg_sel)
            3'd0: rdata = {8'd0, stat};
            3'd1: rdata = {8'd0, track};
            3'd2: rdata = {8'd0, sector};
            default: rdata = {8'd0, data_out ? q_byte : data};
        endcase
    end

    // logical sector of (cylinder, side, sector) on the selected drive
    wire [15:0] lsn_full = ((head * {14'd0, sides}) + {15'd0, side}) * {12'd0, spt} +
                           {8'd0, sector} - 16'd1;
    wire        lsn_ok = sector >= 8'd1 && sector <= {4'd0, spt} && {1'b0, side} < sides &&
                         lsn_full < {5'd0, nsec} && track == head[7:0] && head[15:8] == 8'd0;

    // Type I targets
    wire signed [17:0] seek_t = $signed({2'b0, head}) + $signed({10'd0, data}) - $signed({10'd0, track});
    wire [15:0] seek_target = seek_t < 0 ? 16'd0 : seek_t[15:0];
    logic [31:0] step_ns;
    always_comb begin
        case (wdata[1:0])
            2'd0, 2'd1: step_ns = 6_000_000;
            2'd2: step_ns = 10_000_000;
            default: step_ns = 20_000_000;
        endcase
    end

    // media RAM port
    assign fd_addr  = {drive, copy_lsn, idx[7:0]};
    wire [7:0] r_word = flushing ? idx[7:0] : pos[8:1];
    wire [7:0] q_byte = pos[0] ? q[15:8] : q[7:0];
    always_ff @(posedge clk) begin
        if (b_we) begin
            if (b_be[0]) sbuf_lo[b_wa] <= b_wd[7:0];
            if (b_be[1]) sbuf_hi[b_wa] <= b_wd[15:8];
        end
        q <= {sbuf_hi[r_word], sbuf_lo[r_word]};
        q_word <= r_word;
    end
    always_comb begin
        b_we = 1'b0; b_be = 2'b00; b_wa = idx[7:0]; b_wd = fd_rdata;
        if (filling && fd_ack) begin
            b_we = 1'b1; b_be = 2'b11;
        end else if (ack && wr && reg_sel == 3'd3 && data_in) begin
            b_we = 1'b1; b_wa = pos[8:1];
            b_be = pos[0] ? 2'b10 : 2'b01;
            b_wd = {wdata[7:0], wdata[7:0]};
        end
    end
    // a CPU D103 access comes at least an instruction after pos moved, so q
    // follows pos in time; a write-back word goes out once q holds it
    assign fd_rd    = filling;
    assign fd_wr    = flushing && q_word == idx[7:0];
    assign fd_wdata = q;

    wire signed [31:0] ns = {22'd0, tick_ns};
    // a Type I command's step time, multiplied out the clock after the write
    // (the instruction's tick comes then at the earliest): timing
    logic [15:0] seek_n;
    logic [31:0] seek_step;
    logic        seek_go;
    wire signed [31:0] seek_ns = $signed(seek_step * {16'd0, seek_n});

    task automatic start_type1(input logic [15:0] start, input logic [15:0] target);
        logic [15:0] nsteps;
        nsteps = target > start ? target - start : start - target;
        if (nsteps == 16'd0) nsteps = 16'd1;
        if (drive) head1 <= target; else head0 <= target;
        seek_n <= nsteps;                     // busy_ns = step x steps, set the next clock
        seek_step <= step_ns;
        seek_go <= 1'b1;
    endtask

    always_ff @(posedge clk) begin
        if (rst) begin
            filling <= 1'b0;
            flushing <= 1'b0;
            seek_go <= 1'b0;
            if (ld_we) case (ld_addr)
                5'd0:  select <= ld_data[15:0];
                5'd1:  track <= ld_data[7:0];
                5'd2:  sector <= ld_data[7:0];
                5'd3:  data <= ld_data[7:0];
                5'd4:  status <= ld_data[7:0];
                5'd5:  type1 <= ld_data[0];
                5'd6:  phase <= ld_data;
                5'd7:  busy_ns <= ld_data;
                5'd8:  pend <= ld_data[0];
                5'd9:  pend_write <= ld_data[0];
                5'd10: pend_none <= ld_data[0];
                5'd11: pend_lsn <= ld_data[9:0];
                5'd12: pend_wait <= ld_data;
                5'd13: buf_valid <= ld_data[0];
                5'd14: kind_write <= ld_data[0];
                5'd15: head0 <= ld_data[15:0];
                5'd16: head1 <= ld_data[15:0];
                5'd17: step_out <= ld_data[0];
                default: ;
            endcase
        end else begin
        // sector copy (floppy accesses wait meanwhile; time still runs)
        if (filling && fd_ack) begin
            idx <= idx + 9'd1;
            if (idx == 9'd255) filling <= 1'b0;
        end
        if (fd_wr && fd_ack) begin
            idx <= idx + 9'd1;
            if (idx == 9'd255) flushing <= 1'b0;
        end
        if (ack && wr) begin
            case (reg_sel)
                3'd0: begin
                    if (hi == 4'o15) begin                    // force interrupt
                        buf_valid <= 1'b0;
                        pend <= 1'b0;
                        busy_ns <= 0;
                        status <= 8'd0;
                        type1 <= 1'b1;
                    end else if (status[0]) begin
                        ;                                     // ignored while busy
                    end else if (hi < 4'd8) begin             // Type I
                        type1 <= 1'b1;
                        status <= BUSY | (wdata[3] ? HEAD_LOADED : 8'd0);
                        if (hi == 4'd0) begin                 // restore
                            track <= 8'd0;
                            if (!have) begin
                                status <= BUSY | RNF | (wdata[3] ? HEAD_LOADED : 8'd0);
                                start_type1(head, head);
                            end else
                                start_type1(head, 16'd0);
                        end else if (hi == 4'd1) begin        // seek
                            track <= data;
                            start_type1(head, seek_target);
                        end else begin                        // step, step in, step out
                            logic dir_out;
                            dir_out = hi >= 4'd6 ? 1'b1 : hi >= 4'd4 ? 1'b0 : step_out;
                            step_out <= dir_out;
                            if (wdata[4]) track <= dir_out ? track - 8'd1 : track + 8'd1;
                            start_type1(head, dir_out ? (head == 16'd0 ? 16'd0 : head - 16'd1)
                                                      : head + 16'd1);
                        end
                    end else begin                            // Type II read / write
                        kind_write <= hi == 4'd10;
                        type1 <= 1'b0;
                        if (!have)
                            status <= NOT_READY;
                        else if (hi == 4'd10 && prot)
                            status <= PROTECT;
                        else begin
                            status <= BUSY;
                            pend <= 1'b1;
                            pend_write <= hi == 4'd10;
                            pend_none <= !lsn_ok;
                            pend_lsn <= lsn_full[9:0];
                            pend_wait <= SECTOR_START_NS;
                        end
                    end
                end
                3'd1: track <= wdata[7:0];
                3'd2: sector <= wdata[7:0];
                3'd3: begin
                    data <= wdata[7:0];
                    if (data_in) begin
                        pos <= pos + 10'd1;
                        if (pos == 10'd511) begin             // last byte: write the sector
                            buf_valid <= 1'b0;
                            status <= 8'd0;
                            flushing <= 1'b1;
                            idx <= 9'd0;
                            copy_lsn <= lsn_w;
                        end
                    end
                end
                default: select <= wdata;
            endcase
        end else if (ack && rd && reg_sel == 3'd3 && data_out) begin
            data <= q_byte;
            pos <= pos + 10'd1;
            if (pos == 10'd511) begin
                buf_valid <= 1'b0;
                status <= 8'd0;
            end
        end else if (tick) begin
            phase <= phase + {22'd0, tick_ns} >= REV_NS ? phase + {22'd0, tick_ns} - REV_NS
                                                        : phase + {22'd0, tick_ns};
            if (busy_ns > 0 && !seek_go) begin
                busy_ns <= busy_ns - ns;
                if (busy_ns - ns <= 0) status <= status & ~BUSY;
            end
            if (pend) begin
                if (pend_wait - ns > 0)
                    pend_wait <= pend_wait - ns;
                else begin
                    pend <= 1'b0;
                    if (pend_none) begin
                        buf_valid <= 1'b0;
                        status <= RNF;
                    end else begin
                        buf_valid <= 1'b1;
                        pos <= 10'd0;
                        if (pend_write)
                            lsn_w <= pend_lsn;
                        else begin
                            filling <= 1'b1;
                            idx <= 9'd0;
                            copy_lsn <= pend_lsn;
                        end
                    end
                end
            end
        end
        if (seek_go) begin                    // the step time of a Type I command
            seek_go <= 1'b0;
            busy_ns <= seek_ns - (tick ? ns : 32'sd0);
            if (tick && seek_ns - ns <= 0) status <= status & ~BUSY;
        end
        end
    end
endmodule
