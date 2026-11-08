// System terminal display: the characters the program sends to D50 shown
// as 80 x 24 text on a 640 x 480 picture (8 x 8 font, rows doubled, the
// text area centred: lines 48-431).
//
// Character handling (what Release L MONITOR sends is printable ASCII plus
// CR and LF): bit 7 is ignored; 040-176 are written at the cursor, with a
// pending wrap at column 80 as on a VT100; CR = column 0; LF = next line,
// scrolling at the bottom; BS = left one; HT = next multiple of 8; FF =
// clear and home. Everything else is ignored.
//
// Video: 800 x 525 clocks per frame at one pixel per `ce` (clk/2: 25 MHz
// from 50 MHz, 59.5 Hz). Sync pulses are active high (MiSTer convention).
module term_display #(
    parameter int CE_DIV = 2              // clocks per pixel
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        in_valid,
    input  logic [7:0]  in_data,
    input  logic [1:0]  color,          // 0 green, 1 amber, 2 white

    output logic        ce_pix,
    output logic [7:0]  r,
    output logic [7:0]  g,
    output logic [7:0]  b,
    output logic        hs,
    output logic        vs,
    output logic        hblank,
    output logic        vblank,

    input  logic [11:0] peek_addr,      // simulation: {row (physical), column}
    output logic [7:0]  peek_data,
    output logic [4:0]  top_row         // physical row shown at the top
);
    `include "font8x8.svh"

    localparam int COLS = 80, ROWS = 24;

    // ------------------------------------------------------------ input FIFO
    logic [7:0] fifo [64];
    logic [5:0] f_head, f_tail;
    wire        f_any = f_head != f_tail;
    always_ff @(posedge clk) begin
        if (rst) f_tail <= '0;
        else if (in_valid && f_tail + 6'd1 != f_head) begin
            fifo[f_tail] <= in_data;
            f_tail <= f_tail + 6'd1;
        end
    end

    // ------------------------------------------------------------- text RAM
    // {physical row[4:0], column[6:0]}; written by the writer, read by video
    logic [7:0]  tram [4096];
    logic [11:0] w_addr;
    logic [7:0]  w_data;
    logic        w_we;
    always_ff @(posedge clk) if (w_we) tram[w_addr] <= w_data;

    // ---------------------------------------------------------------- writer
    typedef enum logic [1:0] {W_IDLE, W_CLEAR} wstate_t;
    wstate_t wstate;
    logic [6:0] col;
    logic [4:0] row;            // logical row 0-23
    logic [4:0] top;            // physical row of logical row 0
    logic       wrap;           // pending wrap
    logic [6:0] clr_col;
    logic [4:0] clr_row, clr_end;  // physical rows [clr_row, clr_end] to clear
    assign top_row = top;

    function automatic logic [4:0] phys(input logic [4:0] t, input logic [4:0] lr);
        logic [5:0] s;
        s = 6'(t) + 6'(lr);
        phys = s >= 6'(ROWS) ? 5'(s - 6'(ROWS)) : 5'(s);
    endfunction

    wire [7:0] c = fifo[f_head] & 8'h7f;

    always_ff @(posedge clk) begin
        w_we <= 1'b0;
        if (rst) begin
            f_head <= '0;
            col <= '0;
            row <= '0;
            top <= '0;
            wrap <= 1'b0;
            clr_row <= 5'd0;
            clr_end <= 5'(ROWS - 1);
            clr_col <= '0;
            wstate <= W_CLEAR;                   // clear the screen
        end else case (wstate)
            W_IDLE:
                if (f_any) begin
                    f_head <= f_head + 6'd1;
                    if (c >= 8'o040 && c <= 8'o176) begin
                        if (wrap) begin                          // wrap first
                            col <= 7'd1;
                            wrap <= 1'b0;
                            if (row == 5'(ROWS - 1)) begin
                                w_addr <= {top, 7'd0};
                                top <= phys(top, 5'd1);
                                clr_row <= top; clr_end <= top; clr_col <= 7'd1;
                                wstate <= W_CLEAR;               // rest of the new line
                            end else begin
                                row <= row + 5'd1;
                                w_addr <= {phys(top, row + 5'd1), 7'd0};
                            end
                        end else begin
                            w_addr <= {phys(top, row), col};
                            if (col == 7'(COLS - 1)) wrap <= 1'b1;
                            else col <= col + 7'd1;
                        end
                        w_data <= c;
                        w_we <= 1'b1;
                    end else begin
                        case (c)
                            8'o015: begin col <= '0; wrap <= 1'b0; end
                            8'o012: begin
                                wrap <= 1'b0;
                                if (row == 5'(ROWS - 1)) begin
                                    top <= phys(top, 5'd1);
                                    clr_row <= top; clr_end <= top; clr_col <= '0;
                                    wstate <= W_CLEAR;
                                end else row <= row + 5'd1;
                            end
                            8'o010: begin
                                wrap <= 1'b0;
                                if (col != 7'd0) col <= col - 7'd1;
                            end
                            8'o011: begin
                                wrap <= 1'b0;
                                col <= col >= 7'(COLS - 8) ? 7'(COLS - 1) : (col | 7'd7) + 7'd1;
                            end
                            8'o014: begin
                                col <= '0; row <= '0; wrap <= 1'b0;
                                clr_row <= 5'd0; clr_end <= 5'(ROWS - 1); clr_col <= '0;
                                wstate <= W_CLEAR;
                            end
                            default: ;
                        endcase
                    end
                end
            W_CLEAR: begin                       // blank physical rows clr_row..clr_end
                w_addr <= {clr_row, clr_col};
                w_data <= 8'o040;
                w_we <= 1'b1;
                if (clr_col == 7'(COLS - 1)) begin
                    clr_col <= '0;
                    if (clr_row == clr_end) wstate <= W_IDLE;
                    else clr_row <= clr_row + 5'd1;
                end else clr_col <= clr_col + 7'd1;
            end
            default: wstate <= W_IDLE;
        endcase
    end

    // ----------------------------------------------------------------- video
    logic [$clog2(CE_DIV)-1:0] div;
    always_ff @(posedge clk) div <= div == ($clog2(CE_DIV))'(CE_DIV - 1) ? '0 : div + 1'b1;
    wire ce = div == '0;

    logic [9:0] h, v;
    logic [5:0] frame;
    always_ff @(posedge clk) if (ce) begin
        if (h == 10'd799) begin
            h <= '0;
            if (v == 10'd524) begin v <= '0; frame <= frame + 6'd1; end
            else v <= v + 10'd1;
        end else h <= h + 10'd1;
    end

    // text RAM read, then font read; the output register holds pixel h1
    wire        in_text = v >= 10'd48 && v < 10'd432;
    wire [8:0]  ty = 9'(v - 10'd48);
    wire [4:0]  lrow = ty[8:4];
    wire [2:0]  line = ty[3:1];
    logic [7:0] ch_q, glyph_q;
    logic [2:0] line_q;
    always_ff @(posedge clk) begin
        ch_q <= tram[{phys(top, lrow), h[9:3]}];
        line_q <= line;
        glyph_q <= font8x8({ch_q[6:0], line_q});
        peek_data <= tram[peek_addr];
    end

    // glyph_q holds the glyph of the pixel one behind the counters (h1)
    logic [9:0] h1, v1;
    logic       t1, cur1;
    wire        cursor_here = in_text && lrow == row && h[9:3] == col && line == 3'd7 && frame[5];
    always_ff @(posedge clk) if (ce) begin
        h1 <= h;
        v1 <= v;
        t1 <= in_text && h < 10'd640;
        cur1 <= cursor_here;
    end

    wire on = t1 && (glyph_q[h1[2:0]] ^ cur1);
    always_ff @(posedge clk) if (ce) begin
        hblank <= h1 >= 10'd640;
        vblank <= v1 >= 10'd480;
        hs <= h1 >= 10'd656 && h1 < 10'd752;
        vs <= v1 >= 10'd490 && v1 < 10'd492;
        case (color)
            2'd1:    {r, g, b} <= on ? 24'hffb000 : 24'h000000;
            2'd2:    {r, g, b} <= on ? 24'he0e0e0 : 24'h000000;
            default: {r, g, b} <= on ? 24'h33ff66 : 24'h000000;
        endcase
    end
    assign ce_pix = ce;
endmodule
