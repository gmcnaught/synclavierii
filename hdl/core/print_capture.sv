// The printer's bytes (dev_printer) appended to a capture file on one SD
// image slot (hps_io sd_*, 512-byte blocks; MiSTer slot S6). File format
// (tools/print_render.py): block 0 a header, bytes 0-7 "SYNCPRNT", 8-9
// version 1, 10-13 the number of bytes captured (all big-endian), the rest
// 0; the bytes from block 1 on.
//
// At a mount the header is read: a capture file goes on where it ended (its
// partly filled last block is read back), anything else starts empty. Bytes
// fill one half of a 1 KB buffer; a full half (one block) is written at
// once while the other half fills. When no byte has come for IDLE_CLKS
// clocks the partly filled block and then the header are written, and
// `note` pulses: 1 saved, 2 bytes were lost (no file in the slot, or it is
// read only, or a byte came while a mount was being read), 3 the file is
// full (bytes after its end are lost). Mounting a new image restarts.
module print_capture #(
    parameter int IDLE_CLKS = 12_500_000      // 0.25 s at 50 MHz
) (
    input  logic        clk,
    input  logic        rst,                  // power-on (keeps the file across user resets)

    input  logic        in_valid,
    input  logic [7:0]  in_data,

    input  logic        img_mounted,          // this slot's mount strobe
    input  logic        img_readonly,
    input  logic [63:0] img_size,
    output logic [31:0] sd_lba,
    output logic        sd_rd,
    output logic        sd_wr,
    input  logic        sd_ack,
    input  logic [13:0] sd_buff_addr,
    input  logic [7:0]  sd_buff_dout,
    output logic [7:0]  sd_buff_din,
    input  logic        sd_buff_wr,

    output logic [31:0] count,                // bytes in the file
    output logic        busy,                 // bytes not yet in the file (or an SD transfer)
    output logic [1:0]  note,                 // one-clock event, see above
    output logic        note_valid
);
    localparam logic [2:0] S_NONE = 3'd0, S_HDR_RD = 3'd1, S_BLK_RD = 3'd2, S_IDLE = 3'd3,
                           S_WR = 3'd4, S_HDR_WR = 3'd5;
    logic [2:0]  state;
    logic        acked;                       // the SD side took the request (ack seen)
    logic [31:0] cap;                         // bytes the file holds
    logic        hdr_ok;
    logic [31:0] hdr_count;
    logic        wh;                          // half being filled
    logic [8:0]  wptr;                        // next byte in it
    logic        pend;                        // a full half waits to be written
    logic        pend_half;
    logic [22:0] pend_blk;
    logic        part;                        // the filling half has bytes not written
    logic        hdr_dirty;                   // the header's count is old
    logic        lost, full;
    logic [31:0] idle;
    logic        rd_half;                     // half the SD write reads

    // ---------------------------------------------------------- buffer
    logic [7:0] mem [1024];
    logic [7:0] q, hb;
    wire        fill = state == S_BLK_RD && acked && sd_buff_wr;
    wire        take = in_valid && state != S_NONE && state != S_HDR_RD && state != S_BLK_RD
                       && count != cap;
    always_ff @(posedge clk) begin
        if (fill) mem[{1'b0, sd_buff_addr[8:0]}] <= sd_buff_dout;
        else if (take) mem[{wh, wptr}] <= in_data;
        q <= mem[{rd_half, sd_buff_addr[8:0]}];
    end
    function automatic logic [7:0] hdr_byte(input logic [8:0] a, input logic [31:0] n);
        case (a)
            9'd0: hdr_byte = "S";  9'd1: hdr_byte = "Y";  9'd2: hdr_byte = "N";  9'd3: hdr_byte = "C";
            9'd4: hdr_byte = "P";  9'd5: hdr_byte = "R";  9'd6: hdr_byte = "N";  9'd7: hdr_byte = "T";
            9'd9: hdr_byte = 8'd1;
            9'd10: hdr_byte = n[31:24]; 9'd11: hdr_byte = n[23:16];
            9'd12: hdr_byte = n[15:8];  9'd13: hdr_byte = n[7:0];
            default: hdr_byte = 8'd0;
        endcase
    endfunction
    always_ff @(posedge clk) hb <= hdr_byte(sd_buff_addr[8:0], count);
    assign sd_buff_din = state == S_HDR_WR ? hb : q;

    assign busy = state != S_IDLE && state != S_NONE || pend || part || hdr_dirty;

    wire [63:0] blocks = {9'd0, img_size[63:9]};
    wire        sd_done = acked && !sd_ack;   // the transfer has ended

    always_ff @(posedge clk) begin
        note_valid <= 1'b0;
        if (rst) begin
            state <= S_NONE; sd_rd <= 1'b0; sd_wr <= 1'b0; acked <= 1'b0;
            count <= '0; cap <= '0; pend <= 1'b0; part <= 1'b0; hdr_dirty <= 1'b0;
            lost <= 1'b0; full <= 1'b0; idle <= '0; wh <= 1'b0; wptr <= '0; rd_half <= 1'b0;
        end else if (img_mounted) begin
            sd_rd <= 1'b0; sd_wr <= 1'b0; acked <= 1'b0;
            pend <= 1'b0; part <= 1'b0; hdr_dirty <= 1'b0; full <= 1'b0;
            count <= '0; wh <= 1'b0; wptr <= '0;
            cap <= blocks < 64'd2 ? 32'd0 : blocks >= 64'h0080_0000 ? 32'hFFFF_FE00
                                           : {blocks[22:0] - 23'd1, 9'd0};
            if (img_size[63:10] != 0 && !img_readonly) begin   // at least 2 blocks
                state <= S_HDR_RD; sd_lba <= '0; sd_rd <= 1'b1;
                hdr_ok <= 1'b1; hdr_count <= '0;
            end else
                state <= S_NONE;
        end else begin
            if (sd_ack) begin acked <= 1'b1; sd_rd <= 1'b0; sd_wr <= 1'b0; end
            // ---- bytes in
            if (in_valid) begin
                idle <= '0;
                if (state == S_NONE || state == S_HDR_RD || state == S_BLK_RD) lost <= 1'b1;
                else if (count == cap) full <= 1'b1;
            end else if (idle != IDLE_CLKS) idle <= idle + 1;
            if (take) begin
                count <= count + 32'd1;
                hdr_dirty <= 1'b1;
                if (wptr == 9'd511) begin
                    pend <= 1'b1; pend_half <= wh; pend_blk <= 23'(count >> 9) + 23'd1;
                    wh <= !wh; wptr <= '0; part <= 1'b0;
                end else begin
                    wptr <= wptr + 9'd1; part <= 1'b1;
                end
            end
            // ---- SD side
            case (state)
            S_HDR_RD:
                if (acked && sd_buff_wr) begin
                    if (sd_buff_addr[8:0] < 9'd8 && sd_buff_dout != hdr_byte(sd_buff_addr[8:0], 32'd0))
                        hdr_ok <= 1'b0;
                    if (sd_buff_addr[8:0] == 9'd8 && sd_buff_dout != 8'd0) hdr_ok <= 1'b0;
                    if (sd_buff_addr[8:0] == 9'd9 && sd_buff_dout != 8'd1) hdr_ok <= 1'b0;
                    if (sd_buff_addr[8:0] >= 9'd10 && sd_buff_addr[8:0] <= 9'd13)
                        hdr_count <= {hdr_count[23:0], sd_buff_dout};
                end else if (sd_done) begin
                    acked <= 1'b0;
                    if (hdr_ok && hdr_count != 0) begin
                        count <= hdr_count > cap ? cap : hdr_count;
                        wptr <= hdr_count > cap ? cap[8:0] : hdr_count[8:0];
                        if ((hdr_count > cap ? cap[8:0] : hdr_count[8:0]) != 9'd0) begin
                            sd_lba <= {9'd0, 23'((hdr_count > cap ? cap : hdr_count) >> 9) + 23'd1};
                            sd_rd <= 1'b1;
                            state <= S_BLK_RD;
                        end else state <= S_IDLE;
                    end else state <= S_IDLE;
                end
            S_BLK_RD:
                if (sd_done) begin acked <= 1'b0; state <= S_IDLE; end
            S_IDLE:
                if (pend) begin                       // a full block
                    pend <= 1'b0;
                    rd_half <= pend_half; sd_lba <= {9'd0, pend_blk}; sd_wr <= 1'b1;
                    state <= S_WR;
                end else if (idle == IDLE_CLKS && part) begin       // the block being filled
                    part <= 1'b0;
                    rd_half <= wh; sd_lba <= {9'd0, 23'(count >> 9) + 23'd1}; sd_wr <= 1'b1;
                    state <= S_WR;
                end else if (idle == IDLE_CLKS && hdr_dirty) begin  // then the header
                    hdr_dirty <= 1'b0;
                    sd_lba <= '0; sd_wr <= 1'b1;
                    state <= S_HDR_WR;
                end else if (idle == IDLE_CLKS && (lost || full)) begin
                    note_valid <= 1'b1; note <= lost ? 2'd2 : 2'd3;
                    lost <= 1'b0; full <= 1'b0;
                end
            S_WR:
                if (sd_done) begin acked <= 1'b0; state <= S_IDLE; end
            S_HDR_WR:
                if (sd_done) begin
                    acked <= 1'b0; state <= S_IDLE;
                    if (!lost && !full) begin note_valid <= 1'b1; note <= 2'd1; end
                end
            default:                                  // S_NONE
                if (idle == IDLE_CLKS && lost) begin
                    note_valid <= 1'b1; note <= 2'd2; lost <= 1'b0;
                end
            endcase
        end
    end
endmodule
