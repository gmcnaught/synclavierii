// Floppy media on the MiSTer SD block interface (hps_io sd_*, BLKSZ 512).
//
// One mounted image per drive (F0, F1): the floppy's logical sectors in
// order, 512 bytes each, words big-endian (a floppy-sized slice of a NED
// .simg; `tools/ned_disk.py --floppy` writes one). Logical sector n of the
// floppy is SD block n of the image.
//
// Word port (dev_floppy's fd_* or the boot loader): {drive, lsn[9:0],
// word[7:0]}; hold rd/wr until ack, a one-clock pulse; the clock after an
// ack is ignored (the same handshake as the simulation RAM models). One
// sector is buffered. A miss reads the sector from the SD card first; the
// write of a sector's last word (255) writes it back at once. Waiting costs
// no simulated time (dev_floppy holds floppy accesses while it copies).
module sd_floppy (
    input  logic        clk,
    input  logic        rst,

    input  logic [18:0] addr,
    input  logic        rd,
    input  logic        wr,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,

    output logic [1:0]  present,
    output logic [1:0]  protect,
    output logic [10:0] sectors0,
    output logic [10:0] sectors1,
    output logic        active,         // an SD transfer is in progress (LED)

    input  logic [1:0]  img_mounted,
    input  logic        img_readonly,
    input  logic [63:0] img_size,
    output logic [31:0] sd_lba0,
    output logic [31:0] sd_lba1,
    output logic [1:0]  sd_rd,
    output logic [1:0]  sd_wr,
    input  logic [1:0]  sd_ack,
    input  logic [8:0]  sd_buff_addr,
    input  logic [7:0]  sd_buff_dout,
    output logic [7:0]  sd_buff_din,
    input  logic        sd_buff_wr
);
    typedef enum logic [2:0] {S_IDLE, S_RD, S_RDING, S_WR, S_WRING} state_t;
    state_t state;

    logic        t_valid, t_dirty, t_drive;
    logic [9:0]  t_lsn;

    wire        drive = addr[18];
    wire [9:0]  lsn   = addr[17:8];
    wire [7:0]  w     = addr[7:0];
    wire        hit   = t_valid && t_drive == drive && t_lsn == lsn;
    wire        req   = (rd || wr) && !ack;

    // sector buffer: high and low bytes of each word, one address for both
    // (the CPU side and the SD side never use it in the same state)
    logic [7:0] buf_hi [256];
    logic [7:0] buf_lo [256];
    logic [7:0] q_hi, q_lo;
    logic       sd_side, sd_odd;
    wire [7:0]  b_addr = sd_side ? sd_buff_addr[8:1] : w;
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

    always_ff @(posedge clk) begin
        ack <= 1'b0;
        if (rst) begin
            state <= S_IDLE;
            t_valid <= 1'b0;
            t_dirty <= 1'b0;
            sd_rd <= 2'b00;
            sd_wr <= 2'b00;
            present <= 2'b00;
            protect <= 2'b00;
            sectors0 <= 11'd0;
            sectors1 <= 11'd0;
        end else begin
            for (int d = 0; d < 2; d++)
                if (img_mounted[d]) begin
                    present[d] <= img_size != 64'd0;
                    protect[d] <= img_readonly;
                    if (d == 0) sectors0 <= img_size[63:19] != 0 ? 11'd1024 : 11'(img_size[18:9]);
                    else        sectors1 <= img_size[63:19] != 0 ? 11'd1024 : 11'(img_size[18:9]);
                    if (t_drive == d[0] && !t_dirty) t_valid <= 1'b0;
                end

            case (state)
            S_IDLE:
                if (req) begin
                    if (hit) begin
                        ack <= 1'b1;                     // read data: q next clock
                        if (wr) begin
                            t_dirty <= 1'b1;
                            if (w == 8'd255) state <= S_WR;
                        end
                    end else if (t_valid && t_dirty) begin
                        state <= S_WR;                   // write back first
                    end else begin
                        t_valid <= 1'b0;
                        t_drive <= drive;
                        t_lsn <= lsn;
                        if (drive) sd_lba1 <= {22'd0, lsn}; else sd_lba0 <= {22'd0, lsn};
                        sd_rd[drive] <= 1'b1;
                        state <= S_RD;
                    end
                end
            S_RD:
                if (sd_ack[t_drive]) begin
                    sd_rd <= 2'b00;
                    state <= S_RDING;
                end
            S_RDING:
                if (!sd_ack[t_drive]) begin
                    t_valid <= 1'b1;
                    state <= S_IDLE;
                end
            S_WR: begin
                if (t_drive) sd_lba1 <= {22'd0, t_lsn}; else sd_lba0 <= {22'd0, t_lsn};
                sd_wr[t_drive] <= 1'b1;
                if (sd_ack[t_drive]) begin
                    sd_wr <= 2'b00;
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
