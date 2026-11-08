// System terminal and original panel on a 640 x 480 picture:
//   lines 0-383    the characters the program sends to D50, 80 x 24 text
//                  (8 x 8 font, rows doubled);
//   lines 384-479  the original keyboard's panel, 12 rows of 8 lines: a
//                  rule; the 4-digit display (its 7-segment codes read back
//                  as characters, the decimal point drawn in the cell's
//                  corner) and the units bits in hex; the 128 buttons, 16 a
//                  row (row r = panel word r), each a 4-character label shown
//                  inverted while its light is on; a help line;
//   and the mouse pointer (panel_mouse.sv) once the mouse has moved.
//
// Character handling (what Release L MONITOR sends is printable ASCII plus
// CR and LF): bit 7 is ignored; 040-176 are written at the cursor, with a
// pending wrap at column 80 as on a VT100; CR = column 0; LF = next line,
// scrolling at the bottom; BS = left one; HT = next multiple of 8; FF =
// clear and home. Everything else is ignored.
//
// Video: 800 x 525 pixels per frame, one pixel per `ce` of vclk (on MiSTer
// vclk = 25 MHz and CE_DIV = 1: 59.5 Hz). Sync pulses are active high
// (MiSTer convention). The writer runs on clk; the text RAM is written on
// clk and read on vclk. The cursor and scroll position are read across
// the clock domains as they are: a change may show one frame late.
module term_display #(
    parameter int CE_DIV = 1              // vclk cycles per pixel
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        vclk,
    input  logic        in_valid,
    input  logic [7:0]  in_data,
    input  logic [1:0]  color,          // 0 green, 1 amber, 2 white
    input  logic [15:0] lights [8],     // panel lights, display words (clk domain;
    input  logic [15:0] display [3],    // read on vclk as they are)
    input  logic        ptr_on,
    input  logic [9:0]  ptr_x,
    input  logic [8:0]  ptr_y,

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
    `include "panel_labels.svh"

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
    localparam int DW = CE_DIV > 1 ? $clog2(CE_DIV) : 1;
    logic [DW-1:0] div;
    always_ff @(posedge vclk) div <= div == DW'(CE_DIV - 1) ? '0 : div + 1'b1;
    wire ce = CE_DIV == 1 || div == '0;

    logic [9:0] h, v;
    logic [5:0] frame;
    always_ff @(posedge vclk) if (ce) begin
        if (h == 10'd799) begin
            h <= '0;
            if (v == 10'd524) begin v <= '0; frame <= frame + 6'd1; end
            else v <= v + 10'd1;
        end else h <= h + 10'd1;
    end

    // ------------------------------------------------- panel strip characters
    localparam logic [8*80-1:0] HELP =       // exactly 80 characters
        " Click a button to press it.   MIDI: ch 1-15 keys, ch 16 buttons, prog = timbre ";
    localparam int HELP_LEN = 80;

    // a 7-segment code (bit 0 = segment a ... bit 6 = g) as a character
    function automatic logic [7:0] seg_char(input logic [6:0] sg);
        case (sg)
            7'o077: seg_char = "0"; 7'o006: seg_char = "1"; 7'o133: seg_char = "2";
            7'o117: seg_char = "3"; 7'o146: seg_char = "4"; 7'o155: seg_char = "5";
            7'o174, 7'o175: seg_char = "6"; 7'o047, 7'o007: seg_char = "7";
            7'o177: seg_char = "8"; 7'o147, 7'o157: seg_char = "9";
            7'o100: seg_char = "-"; 7'o000: seg_char = " ";
            7'o171: seg_char = "E"; 7'o120: seg_char = "r"; 7'o163: seg_char = "P";
            7'o070: seg_char = "L"; 7'o166: seg_char = "H"; 7'o167: seg_char = "A";
            7'o071: seg_char = "C"; 7'o136: seg_char = "d"; 7'o161: seg_char = "F";
            7'o134: seg_char = "o"; 7'o124: seg_char = "n"; 7'o034: seg_char = "u";
            7'o170: seg_char = "t"; 7'o156: seg_char = "y"; 7'o076: seg_char = "U";
            default: seg_char = "?";
        endcase
    endfunction

    function automatic logic [7:0] hex_char(input logic [3:0] n);
        hex_char = n < 4'd10 ? 8'h30 + 8'(n) : 8'h37 + 8'(n);
    endfunction

    // the character, inverse flag and decimal point at panel row pr, column c
    logic [7:0] p_ch;
    logic       p_inv, p_dp;
    logic [7:0] seg_byte;
    always_comb begin
        logic [3:0] bcell;
        logic [2:0] k;
        p_ch = 8'h20; p_inv = 1'b0; p_dp = 1'b0;
        bcell = 4'(h[9:3] / 7'd5);
        k = 3'(h[9:3] % 7'd5);
        seg_byte = 8'd0;
        case (pr)
            4'd0: p_ch = 8'h2d;                                   // rule
            4'd1: begin                                           // display, units
                case (h[9:3])
                    7'd1: p_ch = "D"; 7'd2: p_ch = "i"; 7'd3: p_ch = "s"; 7'd4: p_ch = "p";
                    7'd5: p_ch = "l"; 7'd6: p_ch = "a"; 7'd7: p_ch = "y";
                    7'd10: p_ch = "["; 7'd15: p_ch = "]";
                    7'd11: seg_byte = display[1][15:8];
                    7'd12: seg_byte = display[1][7:0];
                    7'd13: seg_byte = display[0][15:8];
                    7'd14: seg_byte = display[0][7:0];
                    7'd19: p_ch = "U"; 7'd20: p_ch = "n"; 7'd21: p_ch = "i"; 7'd22: p_ch = "t";
                    7'd23: p_ch = "s";
                    7'd25: p_ch = hex_char(display[2][15:12]);
                    7'd26: p_ch = hex_char(display[2][11:8]);
                    7'd27: p_ch = hex_char(display[2][7:4]);
                    7'd28: p_ch = hex_char(display[2][3:0]);
                    default: ;
                endcase
                if (h[9:3] >= 7'd11 && h[9:3] <= 7'd14) begin
                    p_ch = seg_char(seg_byte[6:0]);
                    p_dp = seg_byte[7];
                end
            end
            4'd3, 4'd4, 4'd5, 4'd6, 4'd7, 4'd8, 4'd9, 4'd10:     // buttons
                if (k < 3'd4) begin
                    p_ch = panel_label({3'(pr - 4'd3), bcell, k[1:0]});
                    p_inv = lights[3'(pr - 4'd3)][bcell];
                end
            4'd11: p_ch = HELP[8*(HELP_LEN - 1 - int'(h[9:3])) +: 8];
            default: ;
        endcase
    end

    // ------------------------------------------------------- pixel pipeline
    // stage 0 (counters h, v): region and addresses; stage 1: the character
    // (text RAM or panel); stage 2: its glyph row; stage 3: the output.
    // Every stage advances on ce, so the alignment is the same for any CE_DIV.
    wire        in_text  = v < 10'd384;
    wire        in_panel = v >= 10'd384 && v < 10'd480;
    wire [4:0]  lrow = v[8:4];
    wire [3:0]  pr = 4'((v - 10'd384) >> 3);
    wire [2:0]  line = in_text ? v[3:1] : v[2:0];
    wire        cursor_here = in_text && lrow == row && h[9:3] == col && line == 3'd7 && frame[5];

    logic [7:0] tq, pq, glyph;
    logic [2:0] line1;
    logic       text1, inv1, dp1, cur1, vis1, inv2, dp2, cur2, vis2;
    logic [9:0] h1, h2;
    logic [9:0] v1, v2;
    always_ff @(posedge vclk) if (ce) begin
        tq <= tram[{phys(top, lrow), h[9:3]}];               // text RAM: one read port
        pq <= p_ch;
        text1 <= in_text;
        inv1 <= in_panel && p_inv;
        dp1 <= in_panel && p_dp;
        cur1 <= cursor_here;
        vis1 <= (in_text || in_panel) && h < 10'd640;
        line1 <= line;
        h1 <= h; v1 <= v;
        // stage 2
        glyph <= font8x8({(text1 ? tq[6:0] : pq[6:0]), line1}) |
                 (dp1 && line1 >= 3'd6 ? 8'h80 : 8'h00);       // decimal point
        inv2 <= inv1;
        cur2 <= cur1;
        vis2 <= vis1;
        h2 <= h1; v2 <= v1;
    end
    // simulation only (a second read port would keep the RAM out of M10K)
    // synthesis translate_off
    always_ff @(posedge clk) peek_data <= tram[peek_addr];
    // synthesis translate_on

    // mouse pointer: an 8 x 8 arrow with its tip at (ptr_x, ptr_y)
    function automatic logic [7:0] arrow(input logic [2:0] r_);
        case (r_)
            3'd0: arrow = 8'b0000_0001; 3'd1: arrow = 8'b0000_0011;
            3'd2: arrow = 8'b0000_0111; 3'd3: arrow = 8'b0000_1111;
            3'd4: arrow = 8'b0001_1111; 3'd5: arrow = 8'b0000_0111;
            3'd6: arrow = 8'b0000_1101; default: arrow = 8'b0001_1000;
        endcase
    endfunction
    wire [9:0] pdx = h2 - ptr_x;
    wire [9:0] pdy = v2 - {1'b0, ptr_y};
    wire [7:0] arow = arrow(pdy[2:0]);
    wire       ptr_px = ptr_on && pdx < 10'd8 && pdy < 10'd8 && arow[pdx[2:0]];

    wire on = vis2 && (glyph[h2[2:0]] ^ inv2 ^ cur2);
    always_ff @(posedge vclk) if (ce) begin
        hblank <= h2 >= 10'd640;
        vblank <= v2 >= 10'd480;
        hs <= h2 >= 10'd656 && h2 < 10'd752;
        vs <= v2 >= 10'd490 && v2 < 10'd492;
        if (ptr_px && h2 < 10'd640 && v2 < 10'd480) {r, g, b} <= 24'hffffff;
        else case (color)
            2'd1:    {r, g, b} <= on ? 24'hffb000 : 24'h000000;
            2'd2:    {r, g, b} <= on ? 24'he0e0e0 : 24'h000000;
            default: {r, g, b} <= on ? 24'h33ff66 : 24'h000000;
        endcase
    end
    assign ce_pix = ce;
endmodule
