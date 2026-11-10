// D24-D27 SCSI host adaptor and one disk target (sim/devices/scsi.py; the
// evidence and the model are described there).
//   D24 write: with bit 10000 select a D24 board (only board 0, bit 400,
//              exists), else the initiator's data bits 7-0. Read: select
//              bits | the initiator's data bits | the byte the target
//              drives in data-in or status phase.
//   D25 write: the initiator's signals (ATN 1, BSY 2, ACK 4, RST 10, SEL
//              40, ...): RST frees the bus; with the bus free, SEL with BSY
//              released and the target's bit on the data bus selects it;
//              ACK raised by hand while REQ is up moves one byte. Read: the
//              initiator's signals | the target's (BSY, MSG, C/D, I/O, REQ;
//              no REQ while ACK is held).
//   D26 / D27: one byte / two bytes (first in bits 15-8) with the
//              handshake done for the CPU.
// Bus phases and commands exactly as the Python model (TEST UNIT READY,
// REZERO, REQUEST SENSE, READ(6/10), WRITE(6/10), SEEK, INQUIRY, MODE
// SELECT, RESERVE, RELEASE, MODE SENSE, START/STOP, PREVENT/ALLOW, READ
// CAPACITY, VERIFY; others CHECK CONDITION, ILLEGAL REQUEST).
// Disk time (block_ns > 0; sim/devices/scsi.py): a READ's block i arrives
// (i + 1) x block_ns of simulated time after the command; until the block
// under the read position has arrived REQ is low on D25 and a D26/D27 read
// is held (`hold`: the CPU retries while time runs). block_ns = 0: at once.
// Seek time (seek_ns, with disk time; sim/devices/scsi.py): a READ that
// does not start where the last READ or WRITE ended, or goes to the other
// disk, first costs seek_ns. Each READ asks sd_floppy for its first line
// (`hint`), which the SD card delivers during the seek. Paced to real time
// (`line_wait`, the throttle on: the MiSTer), a block whose line is not yet
// buffered (`line_ok`, sd_floppy's probe of `probe_blk`) is also not ready,
// so the CPU polls with time running instead of waiting for the SD card
// with time stopped. Unpaced (simulation, lockstep) the access waits for
// its ack at no simulated time, so the run does not depend on SD latency.
// Two disks: TARGET (W0, sd_floppy drive 3) and TARGET1 (W1, drive 4),
// each answering selection only while its image is mounted; `d_unit` says
// which one the word port is for. A disk is 512-byte blocks of 256
// big-endian words behind the word port; a byte the CPU needs from it is fetched while the
// access waits for its ack, which costs no simulated time.
module dev_scsi #(
    parameter logic [3:0] TARGET = 4'd5,         // W0's SCSI ID
    parameter logic [3:0] TARGET1 = 4'd4         // W1's
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        tick,
    input  logic [9:0]  tick_ns,
    input  logic [19:0] block_ns,     // disk time per block (0: none)
    input  logic [25:0] seek_ns,      // seek time of a non-sequential READ (0: none)
    output logic        hint,         // a READ starts: fetch the line of hint_blk
    output logic [15:0] hint_blk,
    output logic [15:0] probe_blk,    // the block under the read position
    input  logic        line_ok,      // its line is buffered (a clock late)
    input  logic        line_wait,    // hold for line_ok (paced to real time)
    output logic        hold,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D24, 1 D25, 2 D26, 3 D27
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,

    input  logic        present,
    input  logic        protect,
    input  logic [16:0] blocks,
    input  logic        present1,     // W1
    input  logic        protect1,
    input  logic [16:0] blocks1,
    output logic        d_unit,       // the selected disk: 0 W0, 1 W1
    output logic [23:0] d_addr,       // {block[15:0], word[7:0]}
    output logic        d_rd,
    output logic        d_wr,
    output logic [15:0] d_wdata,
    input  logic [15:0] d_rdata,
    input  logic        d_ack
);
    // (Written for Quartus 17: plain state constants, no enum-typed function
    // arguments, no variables declared inside procedural blocks.)
    localparam logic [8:0] ATN = 9'o1, BSY = 9'o2, ACK = 9'o4, RST = 9'o10, MSG = 9'o20,
                           SEL = 9'o40, CD = 9'o100, REQ = 9'o200, IO = 9'o400;
    localparam logic [2:0] P_FREE = 3'd0, P_MSG_OUT = 3'd1, P_COMMAND = 3'd2, P_DATA_IN = 3'd3,
                           P_DATA_OUT = 3'd4, P_STATUS = 3'd5, P_MSG_IN = 3'd6;
    localparam logic [2:0] G_DISK = 3'd0, G_INQ = 3'd1, G_CAP = 3'd2, G_MODE = 3'd3, G_SENSE = 3'd4;
    localparam logic [2:0] Q_IDLE = 3'd0, Q_FETCH = 3'd1, Q_RUN = 3'd2, Q_STORE = 3'd3,
                           Q_EXEC = 3'd4, Q_ACK = 3'd5;
    // INQUIRY data, byte 0 first (highest)
    localparam logic [8*36-1:0] INQ = {8'd0, 8'd0, 8'd1, 8'd1, 8'd31, 8'd0, 8'd0, 8'd0,
                                       "MiSTer  ", "SYNCLAVIER W0   ", "1.0 "};

    logic [2:0]  phase, src, q;
    logic        tsel;                // the selected target: 0 TARGET, 1 TARGET1
    wire  [16:0] dblocks = tsel ? blocks1 : blocks;
    wire         dprotect = tsel ? protect1 : protect;
    assign d_unit = tsel;
    logic [15:0] select_bits;
    logic [7:0]  data_out;
    logic [8:0]  sig_out;
    logic        acked;
    logic [7:0]  cdb [12];
    logic [3:0]  cdb_n;
    logic [7:0]  status, sense_key, last_sense;
    logic [24:0] len, pos;
    logic [16:0] lba;
    logic        out_disk;
    logic [7:0]  wbuf;
    logic        cw_ok;               // cw holds stream word cw_word (disk data)
    logic [23:0] cw_word;
    logic [15:0] cw;
    logic [23:0] st_addr;             // the word being written
    logic [1:0]  nbytes;              // bytes still to move for this access
    logic        is_get, is_peek;
    logic [15:0] put_word;
    logic [15:0] acc;                 // bytes got so far

    // target signals for the phase
    logic [8:0] phase_sig;
    always_comb begin
        case (phase)
            P_MSG_OUT:  phase_sig = BSY | MSG | CD | REQ;
            P_COMMAND:  phase_sig = BSY | CD | REQ;
            P_DATA_IN:  phase_sig = BSY | IO | REQ;
            P_DATA_OUT: phase_sig = BSY | REQ;
            P_STATUS:   phase_sig = BSY | CD | IO | REQ;
            P_MSG_IN:   phase_sig = BSY | MSG | CD | IO | REQ;
            default:    phase_sig = 9'd0;
        endcase
    end

    wire [23:0] want_word = pos[24:1];
    wire [16:0] want_blk  = lba + {1'b0, want_word[23:8]};

    // the byte at pos of a generated reply
    wire [31:0] last_blk = {15'd0, dblocks} - 32'd1;
    logic [7:0] gen;
    always_comb begin
        gen = 8'd0;
        case (src)
            G_INQ: if (pos < 25'd36) gen = INQ[8 * (35 - pos[5:0]) +: 8];
            G_CAP: case (pos[2:0])
                3'd0: gen = last_blk[31:24];
                3'd1: gen = last_blk[23:16];
                3'd2: gen = last_blk[15:8];
                3'd3: gen = last_blk[7:0];
                3'd6: gen = 8'h02;                       // 512
                default: gen = 8'd0;
            endcase
            G_MODE: case (pos[3:0])
                4'd0:  gen = 8'd11;
                4'd3:  gen = 8'd8;
                4'd5:  gen = {7'd0, dblocks[16]};
                4'd6:  gen = dblocks[15:8];
                4'd7:  gen = dblocks[7:0];
                4'd10: gen = 8'h02;
                default: gen = 8'd0;
            endcase
            G_SENSE: case (pos[4:0])
                5'd0: gen = 8'h70;
                5'd2: gen = last_sense;
                5'd7: gen = 8'd10;
                default: gen = 8'd0;
            endcase
            default: gen = 8'd0;
        endcase
    end

    wire [7:0] stream_byte = src == G_DISK ? (pos[0] ? cw[7:0] : cw[15:8]) : gen;
    wire need_fetch = phase == P_DATA_IN && src == G_DISK && !(cw_ok && cw_word == want_word);
    wire [7:0] peek = phase == P_DATA_IN ? stream_byte : (phase == P_STATUS ? status : 8'd0);

    // the byte a get takes, the byte a put gives
    wire [7:0] get_b = phase == P_DATA_IN ? stream_byte :
                       phase == P_STATUS  ? status :
                       phase == P_MSG_IN  ? 8'd0 : 8'o377;
    wire [7:0] put_b = nbytes == 2'd2 ? put_word[15:8] : put_word[7:0];

    // CDB length: from the first byte (put_b while it arrives) or cdb[0]
    function automatic logic [3:0] cdb_len(input logic [7:0] op);
        cdb_len = op[7:5] == 3'd0 ? 4'd6 : (op[7:5] <= 3'd2 ? 4'd10 : 4'd12);
    endfunction
    wire [3:0] cdb_need = cdb_len(cdb_n == 4'd0 ? put_b : cdb[0]);

    // the command, decoded (used in Q_EXEC)
    wire [7:0]  ex_op  = cdb[0];
    wire [31:0] ex_lba = ex_op[5] ? {cdb[2], cdb[3], cdb[4], cdb[5]}
                                  : {11'd0, cdb[1][4:0], cdb[2], cdb[3]};
    wire [16:0] ex_n   = ex_op[5] ? {1'b0, cdb[7], cdb[8]}
                                  : (cdb[4] == 8'd0 ? 17'd256 : {9'd0, cdb[4]});
    wire        ex_range = ex_lba + {15'd0, ex_n} > {15'd0, dblocks};
    wire [24:0] ex_len4  = {17'd0, cdb[4]};

    // disk time
    logic        timed;
    logic [39:0] elapsed, due;
    wire ready = !timed || phase != P_DATA_IN || (elapsed >= due && (!line_wait || line_ok));
    assign probe_blk = want_blk[15:0];

    // where the last READ or WRITE ended
    logic        head_ok, head_t;
    logic [31:0] head_lba;
    wire ex_read = ex_op == 8'h08 || ex_op == 8'h28;
    wire ex_seek = ex_read && block_ns != 20'd0 && !(head_ok && head_t == tsel && head_lba == ex_lba);
    // only before an access starts (its own bytes move pos on while it runs)
    assign hold = sel && rd && reg_sel[1] && phase == P_DATA_IN && !ready && q == Q_IDLE && !ack;

    wire start = sel && (rd || wr) && !ack && q == Q_IDLE && !hold;

    assign d_addr  = q == Q_STORE ? st_addr : {want_blk[15:0], want_word[7:0]};
    assign d_rd    = q == Q_FETCH;
    assign d_wr    = q == Q_STORE;
    assign d_wdata = {wbuf, put_word[7:0]};

    always_ff @(posedge clk) begin
        ack <= 1'b0;
        hint <= 1'b0;
        if (tick && timed && elapsed < 40'hFF_FFFF_FFFF - 40'd1024) elapsed <= elapsed + 40'(tick_ns);
        if (rst) begin
            timed <= 1'b0;
            q <= Q_IDLE;
            phase <= P_FREE;
            src <= G_DISK;
            select_bits <= '0; data_out <= '0; sig_out <= '0; acked <= 1'b0;
            cdb_n <= '0; status <= '0; sense_key <= '0; last_sense <= '0;
            cw_ok <= 1'b0; len <= '0; pos <= '0; out_disk <= 1'b0; tsel <= 1'b0;
            head_ok <= 1'b0; head_t <= 1'b0; head_lba <= '0;
        end else case (q)
        Q_IDLE: if (start) begin
            case (reg_sel)
            2'd0: if (wr) begin
                if (wdata[12]) select_bits <= wdata & 16'o400;
                else data_out <= wdata[7:0];
                q <= Q_ACK;
            end else begin
                is_peek <= 1'b1; nbytes <= 2'd0;
                q <= need_fetch ? Q_FETCH : Q_RUN;
            end
            2'd1: if (rd) begin
                rdata <= {7'd0, sig_out | (phase_sig & (acked || !ready ? ~REQ : 9'h1FF))};
                q <= Q_ACK;
            end else begin
                sig_out <= wdata[8:0];
                if (!wdata[2]) acked <= 1'b0;
                if (wdata[3]) begin                                   // RST
                    phase <= P_FREE; cdb_n <= '0;
                    q <= Q_ACK;
                end else if (phase == P_FREE) begin                   // selection
                    if (wdata[5] && !wdata[1] && ((present && data_out[TARGET[2:0]]) ||
                                                  (present1 && data_out[TARGET1[2:0]]))) begin
                        phase <= wdata[0] ? P_MSG_OUT : P_COMMAND;
                        cdb_n <= '0;
                        tsel <= !(present && data_out[TARGET[2:0]]);
                        cw_ok <= 1'b0;
                    end
                    q <= Q_ACK;
                end else if (wdata[2] && !sig_out[2] && !acked && ready) begin // ACK by hand
                    acked <= 1'b1;
                    is_peek <= 1'b0; nbytes <= 2'd1; acc <= '0;
                    if (phase == P_DATA_IN || phase == P_STATUS || phase == P_MSG_IN) begin
                        is_get <= 1'b1;
                        q <= need_fetch ? Q_FETCH : Q_RUN;
                    end else begin
                        is_get <= 1'b0; put_word <= {8'd0, data_out};
                        q <= Q_RUN;
                    end
                end else q <= Q_ACK;
            end
            default: begin                                            // D26, D27
                is_peek <= 1'b0; acc <= '0;
                nbytes <= reg_sel[0] ? 2'd2 : 2'd1;
                is_get <= rd;
                put_word <= reg_sel[0] ? wdata : {8'd0, wdata[7:0]};
                q <= (rd && need_fetch) ? Q_FETCH : Q_RUN;
            end
            endcase
        end

        Q_FETCH: if (d_ack) begin
            cw <= d_rdata; cw_word <= want_word; cw_ok <= 1'b1;
            q <= Q_RUN;
        end

        Q_RUN: begin
            if (is_peek) begin
                rdata <= select_bits | {8'd0, data_out} | {8'd0, peek};
                q <= Q_ACK;
            end else if (nbytes == 2'd0) begin
                if (is_get) rdata <= reg_sel == 2'd3 ? acc : {8'd0, acc[7:0]};
                q <= Q_ACK;
            end else if (is_get) begin                                // take one byte
                acc <= {acc[7:0], get_b};
                nbytes <= nbytes - 2'd1;
                if (phase == P_DATA_IN) begin
                    pos <= pos + 25'd1;
                    if (pos[8:0] == 9'd511) due <= due + 40'(block_ns);   // into the next block
                    if (pos + 25'd1 == len) phase <= P_STATUS;
                    // the next byte of a D27 read may need the next disk word
                    else if (nbytes == 2'd2 && src == G_DISK && pos[0]) q <= Q_FETCH;
                end else if (phase == P_STATUS) phase <= P_MSG_IN;
                else if (phase == P_MSG_IN) begin phase <= P_FREE; cdb_n <= '0; end
            end else begin                                            // give one byte
                nbytes <= nbytes - 2'd1;
                if (phase == P_MSG_OUT) begin
                    if (put_b[7]) phase <= P_COMMAND;
                    else if (put_b == 8'h06 || put_b == 8'h0C) begin phase <= P_FREE; cdb_n <= '0; end
                end else if (phase == P_COMMAND) begin
                    cdb[cdb_n] <= put_b;
                    cdb_n <= cdb_n + 4'd1;
                    if (cdb_n + 4'd1 == cdb_need) q <= Q_EXEC;
                end else if (phase == P_DATA_OUT) begin
                    pos <= pos + 25'd1;
                    if (!pos[0]) wbuf <= put_b;
                    else if (out_disk) begin
                        put_word <= {8'd0, put_b};
                        st_addr <= {want_blk[15:0], want_word[7:0]};
                        q <= Q_STORE;
                    end
                    if (pos + 25'd1 == len) begin status <= 8'h00; phase <= P_STATUS; end
                end
            end
        end

        Q_STORE: if (d_ack) begin            // a word written (pos already advanced)
            cw_ok <= 1'b0;
            q <= Q_RUN;
        end

        Q_EXEC: begin                        // the command is complete: run it
            timed <= block_ns != 20'd0 && (ex_op == 8'h08 || ex_op == 8'h28);
            elapsed <= '0;
            due <= 40'(block_ns);
            last_sense <= sense_key;
            sense_key <= 8'd0;
            status <= 8'h00;
            cw_ok <= 1'b0;
            pos <= '0;
            out_disk <= 1'b0;
            phase <= P_STATUS;
            q <= Q_RUN;                       // finish the access
            case (ex_op)
            8'h00, 8'h01, 8'h0B, 8'h16, 8'h17, 8'h1B, 8'h1E, 8'h2F: ;
            8'h03: begin
                src <= G_SENSE;
                len <= cdb[4] == 8'd0 ? 25'd4 : (cdb[4] > 8'd18 ? 25'd18 : ex_len4);
                phase <= P_DATA_IN;
            end
            8'h12: if (cdb[4] != 8'd0) begin
                src <= G_INQ; len <= cdb[4] > 8'd36 ? 25'd36 : ex_len4; phase <= P_DATA_IN;
            end
            8'h25: begin src <= G_CAP; len <= 25'd8; phase <= P_DATA_IN; end
            8'h1A: if (cdb[4] != 8'd0) begin
                src <= G_MODE; len <= cdb[4] > 8'd12 ? 25'd12 : ex_len4; phase <= P_DATA_IN;
            end
            8'h15: if (cdb[4] != 8'd0) begin len <= ex_len4; phase <= P_DATA_OUT; end
            8'h08, 8'h0A, 8'h28, 8'h2A: begin
                if (ex_range) begin
                    status <= 8'h02; sense_key <= 8'h05;
                end else if (ex_op[1] && dprotect) begin              // write, read only
                    status <= 8'h02; sense_key <= 8'h07;
                end else if (ex_n != 17'd0) begin
                    lba <= ex_lba[16:0];
                    head_ok <= 1'b1; head_t <= tsel; head_lba <= ex_lba + {15'd0, ex_n};
                    if (ex_seek) due <= 40'(block_ns) + 40'(seek_ns);
                    if (ex_read) begin hint <= 1'b1; hint_blk <= ex_lba[15:0]; end
                    len <= {ex_n[15:0], 9'd0};
                    src <= G_DISK;
                    out_disk <= 1'b1;
                    phase <= ex_op[1] ? P_DATA_OUT : P_DATA_IN;
                end
            end
            default: begin status <= 8'h02; sense_key <= 8'h05; end
            endcase
        end

        Q_ACK: begin
            ack <= 1'b1;
            q <= Q_IDLE;
        end
        default: q <= Q_IDLE;
        endcase
    end
endmodule
