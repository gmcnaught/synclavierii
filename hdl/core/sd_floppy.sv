// SD images on the MiSTer SD block interface (hps_io sd_*, BLKSZ 512):
//   drive 0, 1  floppies F0, F1: the floppy's logical sectors in order,
//               512 bytes each, words big-endian (a floppy-sized slice of a
//               NED .simg; `tools/ned_disk.py --floppy` writes one); logical
//               sector n is SD block n;
//   drive 2     a state image for the boot loader (tools/state_image.py),
//               read only;
//   drive 3     a SCSI disk (W0: for dev_scsi), up to 65536 blocks;
//   drive 4     a second SCSI disk (W1:), the same.
//
// Word port (dev_floppy's fd_*, dev_scsi or the boot loader): {drive[2:0],
// block[15:0], word[7:0]}; hold rd/wr until ack, a one-clock pulse; the clock after an
// ack is ignored (the same handshake as the simulation RAM models). One
// line is buffered: for the SCSI disks (drives 3, 4) 32 blocks (16 KB, aligned,
// cut at the end of the image) read with one SD request (hps_io
// sd_blk_cnt), since each request costs about 0.5 ms on the MiSTer whatever
// its size; for the other drives one block. A miss reads the line from the
// SD card first; the write of a block's last word (255) writes that block
// back at once. Waiting costs no simulated time (dev_floppy holds floppy
// accesses while it copies; dev_scsi waits for its ack).
module sd_floppy (
    input  logic        clk,
    input  logic        rst,
    input  logic [26:0] addr,
    input  logic        rd,
    input  logic        wr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic [4:0]  present,
    output logic [1:0]  protect,
    output logic        protect3,
    output logic [10:0] sectors0,       // floppy sizes (at most 1024)
    output logic [10:0] sectors1,
    output logic [12:0] blocks2,        // state image size (at most 4096)
    output logic [16:0] blocks3,        // SCSI disk sizes (at most 65536)
    output logic [16:0] blocks4,
    output logic        protect4,
    output logic        active,         // an SD transfer is in progress (LED)
    input  logic [4:0]  img_mounted,
    input  logic        img_readonly,
    input  logic [63:0] img_size,
    output logic [31:0] sd_lba0,
    output logic [31:0] sd_lba1,
    output logic [31:0] sd_lba2,
    output logic [31:0] sd_lba3,
    output logic [31:0] sd_lba4,
    output logic [4:0]  sd_rd,
    output logic [4:0]  sd_wr,
    output logic [5:0]  sd_blk_cnt3,    // blocks - 1 of drive 3's / 4's request
    output logic [5:0]  sd_blk_cnt4,
    input  logic [4:0]  sd_ack,
    input  logic [13:0] sd_buff_addr,
    input  logic [7:0]  sd_buff_dout,
    output logic [7:0]  sd_buff_din,
    input  logic        sd_buff_wr
);
    localparam logic [2:0] S_IDLE = 3'd0, S_RD = 3'd1, S_RDING = 3'd2, S_WR = 3'd3, S_WRING = 3'd4;
    logic [2:0]  state;
    logic        t_valid, t_dirty;
    logic [2:0]  t_drive;
    logic [15:0] t_blk;                 // the line's first block
    logic [15:0] t_dblk;                // the block to write back
    wire [2:0]  drive = addr[26:24];
    wire [15:0] blk   = addr[23:8];
    wire [7:0]  w     = addr[7:0];
    wire        line  = drive >= 3'd3;  // 32-block lines
    wire [15:0] lbase = line ? {blk[15:5], 5'd0} : blk;
    wire        hit   = t_valid && t_drive == drive && t_blk == lbase;
    wire        req   = (rd || wr) && !ack;
    // line buffer: high and low bytes of each word; the CPU side uses
    // {block in line, word}, the SD side the request's byte address
    // (the two never use it in the same state)
    logic [7:0] buf_hi [8192];
    logic [7:0] buf_lo [8192];
    logic [7:0] q_hi, q_lo;
    logic       sd_side, sd_odd;
    wire [4:0]  cpu_slot = line ? blk[4:0] : 5'd0;
    wire [4:0]  wb_slot  = t_drive >= 3'd3 ? t_dblk[4:0] : 5'd0;
    wire [12:0] b_addr = state == S_RDING ? sd_buff_addr[13:1]
                       : sd_side ? {wb_slot, sd_buff_addr[8:1]} : {cpu_slot, w};
    wire        we_hi = state == S_IDLE ? (req && hit && wr) : (state == S_RDING && sd_buff_wr && !sd_buff_addr[0]);
    wire        we_lo = state == S_IDLE ? (req && hit && wr) : (state == S_RDING && sd_buff_wr && sd_buff_addr[0]);
    wire [7:0]  d_hi  = state == S_IDLE ? wdata[15:8] : sd_buff_dout;
    wire [7:0]  d_lo  = state == S_IDLE ? wdata[7:0]  : sd_buff_dout;
    assign sd_side = state != S_IDLE;
    always_ff @(posedge clk) begin
        if (we_hi) buf_hi[b_addr] <= d_hi;
        if (we_lo) buf_lo[b_addr] <= d_lo;
        q_hi <= buf_hi[b_addr];
        q_lo <= buf_lo[b_addr];
        sd_odd <= sd_buff_addr[0];
    end
    assign rdata       = {q_hi, q_lo};
    assign sd_buff_din = sd_odd ? q_lo : q_hi;
    assign active      = state != S_IDLE;

    // blocks in a SCSI disk's line at lbase: 32, cut at the end of the image
    wire [16:0] dblocks = drive == 3'd4 ? blocks4 : blocks3;
    wire [16:0] left = dblocks > {1'b0, lbase} ? dblocks - {1'b0, lbase} : 17'd1;
    wire [5:0]  cnt3 = left >= 17'd32 ? 6'd31 : 6'(left - 17'd1);

    task automatic set_lba(input logic [2:0] d, input logic [15:0] b);
        case (d)
            3'd0: sd_lba0 <= {16'd0, b};
            3'd1: sd_lba1 <= {16'd0, b};
            3'd2: sd_lba2 <= {16'd0, b};
            3'd3: sd_lba3 <= {16'd0, b};
            default: sd_lba4 <= {16'd0, b};
        endcase
    endtask

    always_ff @(posedge clk) begin
        ack <= 1'b0;
        if (rst) begin
            state <= S_IDLE;
            t_valid <= 1'b0;
            t_dirty <= 1'b0;
            sd_rd <= 5'b00000;
            sd_wr <= 5'b00000;
            sd_blk_cnt3 <= 6'd0;
            sd_blk_cnt4 <= 6'd0;
            present <= 5'b00000;
            protect4 <= 1'b0;
            blocks4 <= 17'd0;
            protect <= 2'b00;
            protect3 <= 1'b0;
            sectors0 <= 11'd0;
            sectors1 <= 11'd0;
            blocks2 <= 13'd0;
            blocks3 <= 17'd0;
        end else begin
            for (int d = 0; d < 5; d++)
                if (img_mounted[d]) begin
                    present[d] <= img_size != 64'd0;
                    if (d == 0) sectors0 <= img_size[63:19] != 0 ? 11'd1024 : 11'(img_size[18:9]);
                    if (d == 1) sectors1 <= img_size[63:19] != 0 ? 11'd1024 : 11'(img_size[18:9]);
                    if (d == 2) blocks2 <= img_size[63:21] != 0 ? 13'd4096 : 13'(img_size[20:9]);
                    if (d == 3) blocks3 <= img_size[63:25] != 0 ? 17'd65536 : 17'(img_size[24:9]);
                    if (d == 4) blocks4 <= img_size[63:25] != 0 ? 17'd65536 : 17'(img_size[24:9]);
                    if (d == 4) protect4 <= img_readonly;
                    if (d < 2) protect[d] <= img_readonly;
                    if (d == 3) protect3 <= img_readonly;
                    if (t_drive == 3'(d) && !t_dirty) t_valid <= 1'b0;
                end
            case (state)
            S_IDLE:
                if (req) begin
                    if (hit) begin
                        ack <= 1'b1;                     // read data: q next clock
                        if (wr) begin
                            t_dirty <= 1'b1;
                            t_dblk <= blk;
                            if (w == 8'd255) state <= S_WR;
                        end
                    end else if (t_valid && t_dirty) begin
                        state <= S_WR;                   // write back first
                    end else begin
                        t_valid <= 1'b0;
                        t_drive <= drive;
                        t_blk <= lbase;
                        set_lba(drive, lbase);
                        sd_blk_cnt3 <= drive == 3'd3 ? cnt3 : 6'd0;
                        sd_blk_cnt4 <= drive == 3'd4 ? cnt3 : 6'd0;
                        sd_rd[drive] <= 1'b1;
                        state <= S_RD;
                    end
                end
            S_RD:
                if (sd_ack[t_drive]) begin
                    sd_rd <= 5'b00000;
                    state <= S_RDING;
                end
            S_RDING:
                if (!sd_ack[t_drive]) begin
                    t_valid <= 1'b1;
                    state <= S_IDLE;
                end
            S_WR: begin
                set_lba(t_drive, t_dblk);
                sd_blk_cnt3 <= 6'd0;
                sd_blk_cnt4 <= 6'd0;
                sd_wr[t_drive] <= 1'b1;
                if (sd_ack[t_drive]) begin
                    sd_wr <= 5'b00000;
                    state <= S_WRING;
                end
            end
            S_WRING:
                if (!sd_ack[t_drive]) begin
                    t_dirty <= 1'b0;
                    state <= S_IDLE;
                end
            default: state <= S_IDLE;
            endcase
        end
    end
endmodule
