// SD images on the MiSTer SD block interface (hps_io sd_*, BLKSZ 512):
//   drive 0, 1  floppies F0, F1: the floppy's logical sectors in order,
//               512 bytes each, words big-endian (a floppy-sized slice of a
//               NED .simg; `tools/ned_disk.py --floppy` writes one); logical
//               sector n is SD block n;
//   drive 2     a state image for the boot loader (tools/state_image.py),
//               read only;
//   drive 3     a SCSI disk (W0: for dev_scsi), up to 65536 blocks;
//   drive 4     a second SCSI disk (W1:), the same;
//   drive 5     the digital STM source (dig_stm.sv, M18), read only, up to
//               65536 blocks.
//
// Word port (dev_floppy's fd_*, dev_scsi or the boot loader): {drive[2:0],
// block[15:0], word[7:0]}; hold rd/wr until ack, a one-clock pulse; the clock after an
// ack is ignored (the same handshake as the simulation RAM models). Two
// lines are buffered: for the SCSI disks (drives 3, 4) and the STM source
// (drive 5) a line is 32 blocks
// (16 KB, aligned, cut at the end of the image) read with one SD request
// (hps_io sd_blk_cnt); for the other drives one block. After an access to
// a SCSI disk's line the next line is read into the other buffer in the
// background (unless it holds a block still to be written back), so a
// sequential read finds its data there: on the MiSTer a 16 KB request takes
// about 12 ms, and with disk time (dev_scsi block_ns) the CPU reads a line
// in more simulated time than that. A miss reads the line first (waiting
// for a background read to finish); the write of a block's last word (255)
// writes that block back at once. Waiting costs no simulated time
// (dev_floppy holds floppy accesses while it copies; dev_scsi waits for
// its ack). `hint` (dev_scsi, at a READ) asks for the line holding
// (hint_drive, hint_blk) in place of any background read not yet started,
// so it arrives during the READ's seek time; `probe_hit` says (a clock
// late) whether the line holding (probe_drive, probe_blk) is buffered.
module sd_floppy (
    input  logic        clk,
    input  logic        rst,
    input  logic [26:0] addr,
    input  logic        rd,
    input  logic        wr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic [5:0]  present,
    output logic [1:0]  protect,
    output logic        protect3,
    output logic [10:0] sectors0,       // floppy sizes (at most 1024)
    output logic [10:0] sectors1,
    output logic [12:0] blocks2,        // state image size (at most 4096)
    output logic [16:0] blocks3,        // SCSI disk sizes (at most 65536)
    output logic [16:0] blocks4,
    output logic        protect4,
    output logic [16:0] blocks5,        // STM source size (at most 65536)
    output logic        active,         // an SD transfer is in progress (LED)
    input  logic [5:0]  img_mounted,
    input  logic        img_readonly,
    input  logic [63:0] img_size,
    output logic [31:0] sd_lba0,
    output logic [31:0] sd_lba1,
    output logic [31:0] sd_lba2,
    output logic [31:0] sd_lba3,
    output logic [31:0] sd_lba4,
    output logic [31:0] sd_lba5,
    output logic [5:0]  sd_rd,
    output logic [5:0]  sd_wr,
    output logic [5:0]  sd_blk_cnt3,    // blocks - 1 of drive 3's / 4's / 5's request
    output logic [5:0]  sd_blk_cnt4,
    output logic [5:0]  sd_blk_cnt5,
    input  logic [5:0]  sd_ack,
    input  logic [13:0] sd_buff_addr,
    input  logic [7:0]  sd_buff_dout,
    output logic [7:0]  sd_buff_din,
    input  logic        sd_buff_wr,
    input  logic        hint,
    input  logic [2:0]  hint_drive,
    input  logic [15:0] hint_blk,
    input  logic [2:0]  probe_drive,
    input  logic [15:0] probe_blk,
    output logic        probe_hit
);
    localparam logic [2:0] S_IDLE = 3'd0, S_RD = 3'd1, S_RDING = 3'd2, S_WR = 3'd3, S_WRING = 3'd4;
    logic [2:0]  state;                 // the SD side
    logic        v [2];                 // buffer b holds the line (drv[b], base[b])
    logic [2:0]  drv [2];
    logic [15:0] base [2];
    logic        mru;                   // the buffer used last
    logic        fb;                    // the buffer being read into / written back from
    logic [2:0]  f_drive;               // the SD request's drive
    logic        dirty;                 // a block of buffer dbuf waits to be written back
    logic        wb_req;                //   ... now (its last word was written)
    logic        dbuf;
    logic [15:0] dblk;
    logic        pf;                    // a background read is wanted: (pf_drive, pf_base)
    logic [2:0]  pf_drive;
    logic [15:0] pf_base;

    wire [2:0]  drive = addr[26:24];
    wire [15:0] blk   = addr[23:8];
    wire [7:0]  w     = addr[7:0];
    wire        line  = drive >= 3'd3;  // 32-block lines
    wire [15:0] lbase = line ? {blk[15:5], 5'd0} : blk;
    wire        hit0  = v[0] && drv[0] == drive && base[0] == lbase;
    wire        hit1  = v[1] && drv[1] == drive && base[1] == lbase;
    wire        hit   = hit0 || hit1;
    wire        hb    = hit1;           // the hit buffer
    wire [15:0] hbase = {hint_blk[15:5], 5'd0};
    wire        h_have = (v[0] && drv[0] == hint_drive && base[0] == hbase) ||
                         (v[1] && drv[1] == hint_drive && base[1] == hbase) ||
                         ((state == S_RD || state == S_RDING) && drv[fb] == hint_drive && base[fb] == hbase);
    wire [15:0] pbase = {probe_blk[15:5], 5'd0};
    always_ff @(posedge clk)
        probe_hit <= (v[0] && drv[0] == probe_drive && base[0] == pbase) ||
                     (v[1] && drv[1] == probe_drive && base[1] == pbase);
    wire        req   = (rd || wr) && !ack;
    wire        sd_rding = state == S_RD || state == S_RDING;
    wire        sd_wbing = state == S_WR || state == S_WRING;
    // a hit is served unless the buffer is being read into, a write-back
    // uses the read port, or (a write) the SD side uses the write port
    wire        serve = req && hit && !sd_wbing && !(sd_rding && fb == hb) && !(wr && state != S_IDLE)
                        && !wb_req;

    // buffers: {buffer, block in line, word}; high and low bytes apart. One
    // write port (the SD side's reads, or the CPU's writes), one read port
    // (the CPU's reads, or a write-back's)
    logic [7:0] buf_hi [16384];
    logic [7:0] buf_lo [16384];
    logic [7:0] q_hi, q_lo;
    logic       sd_odd;
    wire [4:0]  cpu_slot = line ? blk[4:0] : 5'd0;
    wire [4:0]  wb_slot  = drv[dbuf] >= 3'd3 ? dblk[4:0] : 5'd0;
    wire [13:0] w_addr = state == S_RDING ? {fb, sd_buff_addr[13:1]} : {hb, cpu_slot, w};
    wire        w_fill = state == S_RDING && sd_buff_wr;
    wire        w_cpu  = serve && wr;
    wire        we_hi  = w_fill ? !sd_buff_addr[0] : w_cpu;
    wire        we_lo  = w_fill ? sd_buff_addr[0] : w_cpu;
    wire [7:0]  d_hi   = w_fill ? sd_buff_dout : wdata[15:8];
    wire [7:0]  d_lo   = w_fill ? sd_buff_dout : wdata[7:0];
    wire [13:0] r_addr = sd_wbing ? {dbuf, wb_slot, sd_buff_addr[8:1]} : {hb, cpu_slot, w};
    always_ff @(posedge clk) begin
        if (we_hi) buf_hi[w_addr] <= d_hi;
        if (we_lo) buf_lo[w_addr] <= d_lo;
        q_hi <= buf_hi[r_addr];
        q_lo <= buf_lo[r_addr];
        sd_odd <= sd_buff_addr[0];
    end
    assign rdata       = {q_hi, q_lo};
    assign sd_buff_din = sd_odd ? q_lo : q_hi;
    assign active      = state != S_IDLE;

    // blocks in a SCSI disk's line at b: 32, cut at the end of the image
    function automatic logic [5:0] line_cnt(input logic [2:0] d, input logic [15:0] b);
        logic [16:0] n, left;
        n = d == 3'd5 ? blocks5 : d == 3'd4 ? blocks4 : blocks3;
        left = n > {1'b0, b} ? n - {1'b0, b} : 17'd1;
        line_cnt = left >= 17'd32 ? 6'd31 : 6'(left - 17'd1);
    endfunction
    wire [16:0] dblocks = drive == 3'd5 ? blocks5 : drive == 3'd4 ? blocks4 : blocks3;
    wire [15:0] next_base = lbase + 16'd32;
    wire        next_ok = line && {1'b0, next_base} < dblocks && lbase != 16'hFFE0;

    task automatic set_lba(input logic [2:0] d, input logic [15:0] b);
        case (d)
            3'd0: sd_lba0 <= {16'd0, b};
            3'd1: sd_lba1 <= {16'd0, b};
            3'd2: sd_lba2 <= {16'd0, b};
            3'd3: sd_lba3 <= {16'd0, b};
            3'd4: sd_lba4 <= {16'd0, b};
            default: sd_lba5 <= {16'd0, b};
        endcase
    endtask

    // start an SD read of line (d, b) into buffer bf
    task automatic start_read(input logic bf, input logic [2:0] d, input logic [15:0] b);
        fb <= bf; f_drive <= d;
        v[bf] <= 1'b0; drv[bf] <= d; base[bf] <= b;
        set_lba(d, b);
        sd_blk_cnt3 <= d == 3'd3 ? line_cnt(d, b) : 6'd0;
        sd_blk_cnt4 <= d == 3'd4 ? line_cnt(d, b) : 6'd0;
        sd_blk_cnt5 <= d == 3'd5 ? line_cnt(d, b) : 6'd0;
        sd_rd[d] <= 1'b1;
        state <= S_RD;
    endtask

    always_ff @(posedge clk) begin
        ack <= 1'b0;
        if (rst) begin
            state <= S_IDLE;
            v[0] <= 1'b0; v[1] <= 1'b0; mru <= 1'b0;
            dirty <= 1'b0; wb_req <= 1'b0; pf <= 1'b0;
            sd_rd <= 6'b000000;
            sd_wr <= 6'b000000;
            sd_blk_cnt3 <= 6'd0;
            sd_blk_cnt4 <= 6'd0;
            sd_blk_cnt5 <= 6'd0;
            present <= 6'b000000;
            protect <= 2'b00;
            protect3 <= 1'b0;
            protect4 <= 1'b0;
            sectors0 <= 11'd0;
            sectors1 <= 11'd0;
            blocks2 <= 13'd0;
            blocks3 <= 17'd0;
            blocks4 <= 17'd0;
            blocks5 <= 17'd0;
        end else begin
            for (int d = 0; d < 6; d++)
                if (img_mounted[d]) begin
                    present[d] <= img_size != 64'd0;
                    if (d == 0) sectors0 <= img_size[63:19] != 0 ? 11'd1024 : 11'(img_size[18:9]);
                    if (d == 1) sectors1 <= img_size[63:19] != 0 ? 11'd1024 : 11'(img_size[18:9]);
                    if (d == 2) blocks2 <= img_size[63:21] != 0 ? 13'd4096 : 13'(img_size[20:9]);
                    if (d == 3) blocks3 <= img_size[63:25] != 0 ? 17'd65536 : 17'(img_size[24:9]);
                    if (d == 4) blocks4 <= img_size[63:25] != 0 ? 17'd65536 : 17'(img_size[24:9]);
                    if (d == 5) blocks5 <= img_size[63:25] != 0 ? 17'd65536 : 17'(img_size[24:9]);
                    if (d < 2) protect[d] <= img_readonly;
                    if (d == 3) protect3 <= img_readonly;
                    if (d == 4) protect4 <= img_readonly;
                    for (int b = 0; b < 2; b++)
                        if (drv[b] == 3'(d) && !(dirty && dbuf == 1'(b))) v[b] <= 1'b0;
                    if (pf_drive == 3'(d)) pf <= 1'b0;
                end

            // ---- the CPU side: a hit
            if (serve) begin
                ack <= 1'b1;                          // read data: q next clock
                mru <= hb;
                if (wr) begin
                    dirty <= 1'b1; dbuf <= hb; dblk <= blk;
                    if (w == 8'd255) wb_req <= 1'b1;
                end
                // read the next line into the other buffer in the background
                if (next_ok && !(v[!hb] && drv[!hb] == drive && base[!hb] == next_base)
                        && !(dirty && dbuf == !hb) && !(sd_rding && fb == !hb)) begin
                    pf <= 1'b1; pf_drive <= drive; pf_base <= next_base;
                end
            end

            // ---- the SD side
            case (state)
            S_IDLE:
                if (wb_req || (req && !hit && dirty)) begin   // write a block back
                    set_lba(drv[dbuf], dblk);
                    sd_blk_cnt3 <= 6'd0; sd_blk_cnt4 <= 6'd0; sd_blk_cnt5 <= 6'd0;
                    sd_wr[drv[dbuf]] <= 1'b1;
                    state <= S_WR;
                end else if (req && !hit) begin               // a miss
                    start_read(!mru, drive, lbase);
                    pf <= 1'b0;
                end else if (pf && !serve) begin              // background read
                    pf <= 1'b0;
                    if (!(dirty && dbuf == !mru)) start_read(!mru, pf_drive, pf_base);
                end
            S_RD:
                if (sd_ack[f_drive]) begin
                    sd_rd <= 6'b000000;
                    state <= S_RDING;
                end
            S_RDING:
                if (!sd_ack[f_drive]) begin
                    v[fb] <= 1'b1;
                    state <= S_IDLE;
                end
            S_WR:
                if (sd_ack[drv[dbuf]]) begin
                    sd_wr <= 6'b000000;
                    state <= S_WRING;
                end
            S_WRING:
                if (!sd_ack[drv[dbuf]]) begin
                    dirty <= 1'b0;
                    wb_req <= 1'b0;
                    state <= S_IDLE;
                end
            default: state <= S_IDLE;
            endcase
            // a READ's first line, ahead of any background read not started
            // (after the SD side, which may have just taken pf)
            if (hint && hint_drive >= 3'd3 && !h_have) begin
                pf <= 1'b1; pf_drive <= hint_drive; pf_base <= hbase;
            end
        end
    end
endmodule
