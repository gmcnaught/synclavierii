// System terminal and original panel on a 640 x 480 picture:
//   lines 0-383    the characters the program sends to D50, 80 x 24 text
//                  (8 x 8 font, rows doubled);
//   lines 384-479  the original keyboard's panel, 12 rows of 8 lines: a
//                  rule; the 4-digit display, drawn as 7 segments (any
//                  pattern, decimal point in the cell's corner) and the units
//                  bits in hex; the 128 buttons, 16 a
//                  row (row r = panel word r), each a 4-character label shown
//                  inverted while its light is on; a help line; and a status
//                  line: real time given up by the throttle (us) and audio
//                  FIFO underruns/overruns, in hex;
//   and the mouse pointer (panel_mouse.sv) once the mouse has moved.
// With `vpk` set the strip shows the velocity keyboard (D130) panel
// instead, 12 rows of 8 lines: the 2 x 16-character display as two
// bracketed fields (characters outside 20-7E shown as spaces; decimal
// points not shown); the status line; and the 160 buttons, 16 a row (row r
// = PBN 16r..16r+15), each a 4-character label inverted while its light is
// on, or every other ~0.54 s (32 frames) while it blinks. vpk_lights is
// indexed by light address = (PBN & 15) + 144 - (PBN & ~15), states 0 off,
// 1 on, 2 blink (3 = on). No rule or help line.
//
// Character handling: the VT100 subset (and VT640 graphics passages skipped)
// that Release L's programs use, exactly as tools/vt100.py (the reference
// model; tests/hdl/test_board.py compares pictures): printable characters
// with a pending wrap at column 80; CR, LF/VT/FF, BS, HT; ESC [ ... H f A B C
// D J K m (reverse video); ESC # 3/4/6/5 line attributes (double height,
// double width); ESC ( 0 / B line-drawing set (font codes 0x00-0x1F);
// ESC 7 8 D E M c; ESC = / > keypad application / numeric mode (output
// keypad_app, for ps2_ascii); GS starts Tektronix graphics, skipped up to
// CAN.
// A cell is {reverse, character[6:0]}.
//
// VT640 mode (`vt640`, from the state image; docs/devices/vt640-graphics-
// terminal.md): GS/FS and every byte while in a graphics mode go to the
// graphics plane (tek_plane.sv); the terminal fills 640 x 480: text row r
// on lines 20r-20r+19 (glyph doubled on lines 20r+2-20r+17), column c from
// pixel 8 + ceil(7.5c), 8 pixels wide for even c, 7 for odd (font column 7
// dropped); double-width columns 15 pixels; reverse inverts the cell's 20
// lines; text OR graphics. No panel strip (with `panel_over`: the panel
// over lines 384-479) and no core pointer outside it: SYN-5.3 draws its
// own cursor. As tools/vt100.py Terminal(vt640=True).render().
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
    input  logic [31:0] lag_us,         // real-time health (hex on panel row 2)
    input  logic [15:0] underruns,
    input  logic [15:0] overruns,
    input  logic [15:0] midi_count,     // MIDI bytes received, the last, framing errors
    input  logic [7:0]  midi_last,
    input  logic [15:0] midi_errs,
    input  logic        midi_alt,       // MIDI line at 9600 rather than 31250
    input  logic        stall_view,     // status line: lag_us by cause (able_system.sv STALL_*)
    input  logic [23:0] stall_us [7],
    input  logic        vpk,            // show the VPK panel (else the ORK's)
    input  logic [1:0]  vpk_lights [160], // by light address (clk domain, read as they are)
    input  logic [7:0]  vpk_chars [32],   // display: 0-15 upper line, 16-31 lower
    input  logic        vt640,          // VT640 graphics terminal (a state image's choice)
    input  logic        panel_over,     // VT640: show the panel strip over lines 384-479

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
    output logic [4:0]  top_row,        // physical row shown at the top
    output logic        keypad_app      // ESC = seen (ESC >, ESC c, reset: cleared)
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
    typedef enum logic [2:0] {S_NORM, S_ESC, S_CSI, S_HASH, S_G0, S_G1, S_TEK} pstate_t;
    pstate_t ps;
    typedef enum logic [0:0] {W_IDLE, W_ERASE} wstate_t;
    wstate_t wstate;
    logic [6:0] col;
    logic [4:0] row;            // logical row 0-23
    logic [4:0] top;            // physical row of logical row 0
    logic       wrap;           // pending wrap
    logic       rev, gfx;       // reverse video; line-drawing set in G0
    logic [6:0] sv_col;
    logic [4:0] sv_row;
    logic       sv_rev;
    logic [7:0] prm [4];        // CSI parameters
    logic [1:0] pn;
    logic       priv;
    logic [1:0] rattr [ROWS];   // line attribute by physical row: 0 single,
                                // 1 double-height top, 2 bottom, 3 double width
    // erase from logical (er_row, er_col) to (er_end_row, er_end_col)
    logic [4:0] er_row, er_end_row;
    logic [6:0] er_col, er_end_col, er_rs;   // er_rs: first column of this row
    assign top_row = top;

    function automatic logic [4:0] phys(input logic [4:0] t, input logic [4:0] lr);
        logic [5:0] s;
        s = 6'(t) + 6'(lr);
        phys = s >= 6'(ROWS) ? 5'(s - 6'(ROWS)) : 5'(s);
    endfunction

    // physical rows of the erase position and the cursor (as wires: a function
    // call in a non-blocking LHS index trips Verilator 5.032)
    wire [4:0] er_prow  = phys(top, er_row);
    wire [4:0] cur_prow = phys(top, row);

    wire [7:0] c = fifo[f_head] & 8'h7f;
    wire [6:0] ch7 = gfx && c >= 8'h5f && c <= 8'h7e ? 7'(c - 8'h5f) : c[6:0];
    wire [6:0] er_row_end = er_row == er_end_row ? er_end_col : 7'(COLS - 1);

    // parameter digits: p * 10 + d, at most 255
    wire [11:0] p_next = {4'd0, prm[pn]} * 12'd10 + {8'd0, c[3:0]};
    wire [7:0]  p0 = prm[0], p1 = prm[1];
    wire [7:0]  n1 = p0 == 8'd0 ? 8'd1 : p0;               // count, default 1
    logic       m_rev;
    always_comb begin                                       // SGR: 0 normal, 7 reverse
        m_rev = rev;
        for (int i = 0; i < 4; i++)
            if (i <= int'(pn)) begin
                if (prm[i] == 8'd0) m_rev = 1'b0;
                else if (prm[i] == 8'd7) m_rev = 1'b1;
            end
    end

    task automatic start_erase(input logic [4:0] r0, input logic [6:0] c0,
                               input logic [4:0] r1, input logic [6:0] c1);
        er_row <= r0; er_col <= c0; er_rs <= c0;
        er_end_row <= r1; er_end_col <= c1;
        wstate <= W_ERASE;
    endtask

    // VT640 graphics plane
    logic        tek_ready, tek_active;
    logic [14:0] g_vaddr;
    logic [15:0] g_vq;
    wire to_tek = vt640 && (tek_active || c == 8'h1c || c == 8'h1d) && (ps == S_NORM || ps == S_TEK);

    always_ff @(posedge clk) begin
        w_we <= 1'b0;
        if (rst) begin
            f_head <= '0;
            col <= '0; row <= '0; top <= '0;
            wrap <= 1'b0; rev <= 1'b0; gfx <= 1'b0;
            sv_col <= '0; sv_row <= '0; sv_rev <= 1'b0;
            keypad_app <= 1'b0;
            ps <= S_NORM;
            for (int i = 0; i < ROWS; i++) rattr[i] <= 2'd0;
            start_erase(5'd0, 7'd0, 5'(ROWS - 1), 7'(COLS - 1));   // clear the screen
        end else case (wstate)
            W_ERASE: begin
                w_addr <= {phys(top, er_row), er_col};
                w_data <= 8'h20;
                w_we <= 1'b1;
                if (er_col == er_row_end) begin
                    if (er_rs == 7'd0 && er_row_end == 7'(COLS - 1))
                        rattr[er_prow] <= 2'd0;          // whole row erased
                    if (er_row == er_end_row) wstate <= W_IDLE;
                    else begin
                        er_row <= er_row + 5'd1;
                        er_col <= '0;
                        er_rs <= '0;
                    end
                end else er_col <= er_col + 7'd1;
            end

            default: if (f_any && to_tek) begin                     // W_IDLE: graphics byte
                if (tek_ready) f_head <= f_head + 6'd1;
            end else if (f_any) begin                               // W_IDLE: next byte
                f_head <= f_head + 6'd1;
                case (ps)
                S_TEK: if (c == 8'h18) ps <= S_NORM;

                S_ESC: begin
                    ps <= S_NORM;
                    case (c)
                        8'h5b: begin                                // [
                            ps <= S_CSI; pn <= '0; priv <= 1'b0;
                            for (int i = 0; i < 4; i++) prm[i] <= '0;
                        end
                        8'h23: ps <= S_HASH;                        // #
                        8'h28: ps <= S_G0;                          // (
                        8'h29: ps <= S_G1;                          // )
                        8'h37: begin sv_row <= row; sv_col <= col; sv_rev <= rev; end
                        8'h38: begin row <= sv_row; col <= sv_col; rev <= sv_rev; wrap <= 1'b0; end
                        8'h44, 8'h45: begin                         // D index, E next line
                            wrap <= 1'b0;
                            if (c == 8'h45) col <= '0;
                            if (row == 5'(ROWS - 1)) begin
                                top <= phys(top, 5'd1);
                                start_erase(5'(ROWS - 1), 7'd0, 5'(ROWS - 1), 7'(COLS - 1));
                            end else row <= row + 5'd1;
                        end
                        8'h4d: begin                                // M reverse index
                            wrap <= 1'b0;
                            if (row != 5'd0) row <= row - 5'd1;
                        end
                        8'h3d: keypad_app <= 1'b1;                  // = keypad application
                        8'h3e: keypad_app <= 1'b0;                  // > keypad numeric
                        8'h63: begin                                // c reset
                            keypad_app <= 1'b0;
                            col <= '0; row <= '0; wrap <= 1'b0; rev <= 1'b0; gfx <= 1'b0;
                            sv_col <= '0; sv_row <= '0; sv_rev <= 1'b0;
                            start_erase(5'd0, 7'd0, 5'(ROWS - 1), 7'(COLS - 1));
                        end
                        default: ;
                    endcase
                end

                S_HASH: begin
                    ps <= S_NORM;
                    case (c)
                        8'h33: rattr[cur_prow] <= 2'd1;       // 3: double height, top
                        8'h34: rattr[cur_prow] <= 2'd2;       // 4: bottom
                        8'h36: rattr[cur_prow] <= 2'd3;       // 6: double width
                        8'h35: rattr[cur_prow] <= 2'd0;       // 5: single
                        default: ;
                    endcase
                end

                S_G0: begin ps <= S_NORM; gfx <= c == 8'h30; end
                S_G1: ps <= S_NORM;

                S_CSI:
                    if (c >= 8'h30 && c <= 8'h39)
                        prm[pn] <= p_next > 12'd255 ? 8'd255 : p_next[7:0];
                    else if (c == 8'h3b) begin
                        if (pn != 2'd3) pn <= pn + 2'd1;
                    end else if (c == 8'h3f) priv <= 1'b1;
                    else if (c >= 8'h40 && c <= 8'h7e) begin
                        ps <= S_NORM;
                        wrap <= 1'b0;
                        if (!priv) case (c)
                            8'h48, 8'h66: begin                     // H f
                                row <= p0 == 8'd0 ? 5'd0 : p0 > 8'(ROWS) ? 5'(ROWS - 1) : 5'(p0 - 8'd1);
                                col <= p1 == 8'd0 ? 7'd0 : p1 > 8'(COLS) ? 7'(COLS - 1) : 7'(p1 - 8'd1);
                            end
                            8'h41: row <= n1 > 8'(row) ? 5'd0 : row - 5'(n1);
                            8'h42: row <= 8'(row) + n1 > 8'(ROWS - 1) ? 5'(ROWS - 1) : row + 5'(n1);
                            8'h43: col <= 8'(col) + n1 > 8'(COLS - 1) ? 7'(COLS - 1) : col + 7'(n1);
                            8'h44: col <= n1 > 8'(col) ? 7'd0 : col - 7'(n1);
                            8'h4a: case (p0)                        // J
                                8'd0: start_erase(row, col, 5'(ROWS - 1), 7'(COLS - 1));
                                8'd1: start_erase(5'd0, 7'd0, row, col);
                                8'd2: start_erase(5'd0, 7'd0, 5'(ROWS - 1), 7'(COLS - 1));
                                default: ;
                            endcase
                            8'h4b: case (p0)                        // K
                                8'd0: start_erase(row, col, row, 7'(COLS - 1));
                                8'd1: start_erase(row, 7'd0, row, col);
                                8'd2: start_erase(row, 7'd0, row, 7'(COLS - 1));
                                default: ;
                            endcase
                            8'h6d: rev <= m_rev;                    // m
                            default: ;
                        endcase
                    end

                default:                                            // S_NORM
                    if (c >= 8'h20 && c <= 8'h7e) begin
                        if (wrap) begin                             // wrap first
                            wrap <= 1'b0;
                            col <= 7'd1;
                            if (row == 5'(ROWS - 1)) begin
                                w_addr <= {top, 7'd0};              // new bottom row
                                rattr[top] <= 2'd0;
                                top <= phys(top, 5'd1);
                                start_erase(5'(ROWS - 1), 7'd1, 5'(ROWS - 1), 7'(COLS - 1));
                            end else begin
                                row <= row + 5'd1;
                                w_addr <= {phys(top, row + 5'd1), 7'd0};
                            end
                        end else begin
                            w_addr <= {phys(top, row), col};
                            if (col == 7'(COLS - 1)) wrap <= 1'b1;
                            else col <= col + 7'd1;
                        end
                        w_data <= {rev, ch7};
                        w_we <= 1'b1;
                    end else case (c)
                        8'h0d: begin col <= '0; wrap <= 1'b0; end
                        8'h0a, 8'h0b, 8'h0c: begin
                            wrap <= 1'b0;
                            if (row == 5'(ROWS - 1)) begin
                                top <= phys(top, 5'd1);
                                start_erase(5'(ROWS - 1), 7'd0, 5'(ROWS - 1), 7'(COLS - 1));
                            end else row <= row + 5'd1;
                        end
                        8'h08: begin
                            wrap <= 1'b0;
                            if (col != 7'd0) col <= col - 7'd1;
                        end
                        8'h09: begin
                            wrap <= 1'b0;
                            col <= col >= 7'(COLS - 8) ? 7'(COLS - 1) : (col | 7'd7) + 7'd1;
                        end
                        8'h1b: ps <= S_ESC;
                        8'h1d: ps <= S_TEK;
                        default: ;
                    endcase
                endcase
            end
        endcase
    end

    // ----------------------------------------------------------------- video
    localparam int DW = CE_DIV > 1 ? $clog2(CE_DIV) : 1;
    logic [DW-1:0] div;
    always_ff @(posedge vclk) div <= div == DW'(CE_DIV - 1) ? '0 : div + 1'b1;
    wire ce = CE_DIV == 1 || div == '0;

    // the graphics plane (its writer side is fed by the writer above)
    tek_plane tek (
        .clk, .rst, .in_valid(f_any && to_tek && wstate == W_IDLE), .in_data(c),
        .ready(tek_ready), .active(tek_active),
        .vclk, .v_ce(ce), .v_addr(g_vaddr), .v_q(g_vq)
    );

    logic [9:0] h, v;
    logic [5:0] frame;
    logic [4:0] trow, vln;               // VT640: text row and line in it (20 lines a row)
    logic [6:0] vtc;                     // VT640: text column at pixel h, and pixel in it
    logic [2:0] vto;
    always_ff @(posedge vclk) if (ce) begin
        if (h == 10'd799) begin
            h <= '0;
            if (v == 10'd524) begin v <= '0; frame <= frame + 6'd1; trow <= '0; vln <= '0; end
            else begin
                v <= v + 10'd1;
                if (vln == 5'd19) begin vln <= '0; trow <= trow + 5'd1; end
                else vln <= vln + 5'd1;
            end
        end else h <= h + 10'd1;
        if (h == 10'd7) begin vtc <= '0; vto <= '0; end           // pixel 8 is column 0's first
        else if (vto == (vtc[0] ? 3'd6 : 3'd7)) begin vtc <= vtc + 7'd1; vto <= '0; end
        else vto <= vto + 3'd1;
    end

    // ------------------------------------------------- panel strip characters
    localparam logic [8*80-1:0] HELP =       // exactly 80 characters
        " Click a button to press it.   MIDI: ch 1-15 keys, ch 16 buttons, prog = timbre ";
    localparam int HELP_LEN = 80;

    function automatic logic [7:0] hex_char(input logic [3:0] n);
        hex_char = n < 4'd10 ? 8'h30 + 8'(n) : 8'h37 + 8'(n);
    endfunction

    // stall view: seven fields of 11 columns from column 1, "Fch 00ABCD "
    // (label, space, microseconds in hex, space)
    localparam logic [8*21-1:0] STALL_LABELS = "FchSCSPlyXm IO FM Run";
    wire [6:0]  stc_col = h[9:3] - 7'd1;
    wire [2:0]  stc_f   = 3'(stc_col / 7'd11);
    wire [3:0]  stc_k   = 4'(stc_col % 7'd11);
    wire [23:0] stc_val = stall_us[stc_f];
    logic [7:0] stc_ch;
    always_comb begin
        stc_ch = 8'h20;
        if (h[9:3] >= 7'd1 && h[9:3] <= 7'd77) begin
            if (stc_k < 4'd3) stc_ch = STALL_LABELS[8*(20 - 3*int'(stc_f) - int'(stc_k)) +: 8];
            else if (stc_k >= 4'd4 && stc_k <= 4'd9)
                stc_ch = hex_char(stc_val[4*(9 - int'(stc_k)) +: 4]);
        end
    end

    // the status line's character at column h[9:3]
    logic [7:0] st_ch;
    always_comb begin
        st_ch = 8'h20;
        if (stall_view) st_ch = stc_ch;
        else case (h[9:3])
            7'd1: st_ch = "L"; 7'd2: st_ch = "a"; 7'd3: st_ch = "g"; 7'd4: st_ch = " ";
            7'd5: st_ch = "u"; 7'd6: st_ch = "s";
            7'd8: st_ch = hex_char(lag_us[31:28]);  7'd9: st_ch = hex_char(lag_us[27:24]);
            7'd10: st_ch = hex_char(lag_us[23:20]); 7'd11: st_ch = hex_char(lag_us[19:16]);
            7'd12: st_ch = hex_char(lag_us[15:12]); 7'd13: st_ch = hex_char(lag_us[11:8]);
            7'd14: st_ch = hex_char(lag_us[7:4]);   7'd15: st_ch = hex_char(lag_us[3:0]);
            7'd19: st_ch = "U"; 7'd20: st_ch = "n"; 7'd21: st_ch = "d"; 7'd22: st_ch = "e";
            7'd23: st_ch = "r"; 7'd24: st_ch = "r"; 7'd25: st_ch = "u"; 7'd26: st_ch = "n";
            7'd28: st_ch = hex_char(underruns[15:12]); 7'd29: st_ch = hex_char(underruns[11:8]);
            7'd30: st_ch = hex_char(underruns[7:4]);   7'd31: st_ch = hex_char(underruns[3:0]);
            7'd35: st_ch = "O"; 7'd36: st_ch = "v"; 7'd37: st_ch = "e"; 7'd38: st_ch = "r";
            7'd39: st_ch = "r"; 7'd40: st_ch = "u"; 7'd41: st_ch = "n";
            7'd43: st_ch = hex_char(overruns[15:12]); 7'd44: st_ch = hex_char(overruns[11:8]);
            7'd45: st_ch = hex_char(overruns[7:4]);   7'd46: st_ch = hex_char(overruns[3:0]);
            7'd50: st_ch = "M"; 7'd51: st_ch = "I"; 7'd52: st_ch = "D"; 7'd53: st_ch = "I";
            7'd55: st_ch = hex_char(midi_count[15:12]); 7'd56: st_ch = hex_char(midi_count[11:8]);
            7'd57: st_ch = hex_char(midi_count[7:4]);   7'd58: st_ch = hex_char(midi_count[3:0]);
            7'd60: st_ch = hex_char(midi_last[7:4]);    7'd61: st_ch = hex_char(midi_last[3:0]);
            7'd63: st_ch = "E"; 7'd64: st_ch = "r"; 7'd65: st_ch = "r";
            7'd67: st_ch = hex_char(midi_errs[15:12]);  7'd68: st_ch = hex_char(midi_errs[11:8]);
            7'd69: st_ch = hex_char(midi_errs[7:4]);    7'd70: st_ch = hex_char(midi_errs[3:0]);
            7'd72: st_ch = midi_alt ? "9" : "3";
            7'd73: st_ch = midi_alt ? "k" : "1";
            7'd74: st_ch = midi_alt ? "6" : "k";
            default: ;
        endcase
    end

    wire [3:0] pr = 4'((v - 10'd384) >> 3);                  // panel row
    // button cell (40 pixels) and character in it (0-3 label, 4 gap)
    wire [3:0] bcell = 4'(h[9:3] / 7'd5);
    wire [2:0] k = 3'(h[9:3] % 7'd5);

    // VPK: the display character at column h[9:3] (11-26 upper, 29-44 lower)
    wire [4:0] vd_idx = h[9:3] <= 7'd26 ? 5'(h[9:3] - 7'd11) : 5'(h[9:3] - 7'd13);
    wire [7:0] vd_raw = vpk_chars[vd_idx];
    wire [7:0] vd_ch  = vd_raw >= 8'h20 && vd_raw <= 8'h7e ? vd_raw : 8'h20;
    // VPK button row pr - 2: PBN {vrow, bcell}, light address {9 - vrow, bcell}
    wire [3:0] vrow = 4'(pr - 4'd2);
    wire [7:0] vla  = pr >= 4'd2 ? {4'd9 - vrow, bcell} : 8'd0;
    wire [1:0] vst  = vpk_lights[vla];
    wire [9:0] vl_addr = {vrow, bcell, k[1:0]};

    // the character, inverse flag and decimal point at panel row pr, column c;
    // p_vlab: the character is the VPK label ROM's (read a clock later)
    logic [7:0] p_ch;
    logic       p_inv, p_dp, p_seg, p_vlab;
    logic [7:0] seg_byte;
    always_comb begin
        p_ch = 8'h20; p_inv = 1'b0; p_dp = 1'b0; p_seg = 1'b0; p_vlab = 1'b0;
        seg_byte = 8'd0;
        if (vpk) case (pr)
            4'd0: begin                                           // display
                case (h[9:3])
                    7'd1: p_ch = "D"; 7'd2: p_ch = "i"; 7'd3: p_ch = "s"; 7'd4: p_ch = "p";
                    7'd5: p_ch = "l"; 7'd6: p_ch = "a"; 7'd7: p_ch = "y";
                    7'd10, 7'd28: p_ch = "[";
                    7'd27, 7'd45: p_ch = "]";
                    default: ;
                endcase
                if ((h[9:3] >= 7'd11 && h[9:3] <= 7'd26) || (h[9:3] >= 7'd29 && h[9:3] <= 7'd44))
                    p_ch = vd_ch;
            end
            4'd1: p_ch = st_ch;                                   // status
            default:                                              // buttons
                if (k < 3'd4) begin
                    p_vlab = 1'b1;
                    p_inv = vst[0] || (vst[1] && frame[5]);
                end
        endcase
        else case (pr)
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
                    p_seg = 1'b1;
                    p_dp = seg_byte[7];
                end
            end
            4'd2: p_ch = st_ch;                                   // status, hex
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
    wire        p_over   = vt640 && panel_over && v >= 10'd384 && v < 10'd480;
    wire        in_text  = vt640 ? v < 10'd480 && !p_over : v < 10'd384;
    wire        in_panel = vt640 ? p_over : v >= 10'd384 && v < 10'd480;
    wire [4:0]  lrow = vt640 ? trow : v[8:4];
    wire [4:0]  prow = phys(top, lrow);
    wire [1:0]  ra   = in_text ? rattr[prow] : 2'd0;     // this row's line attribute
    wire [6:0]  tcol = vt640 ? (ra != 2'd0 ? {1'b0, vtc[6:1]} : vtc)
                             : (ra != 2'd0 ? {1'b0, h[9:4]} : h[9:3]);
    wire [4:0]  vg   = vln - 5'd2;                       // VT640: glyph line 0-15
    wire [2:0]  line = !in_text ? v[2:0] :
                       vt640 ? (ra == 2'd1 ? {1'b0, vg[3:2]} : ra == 2'd2 ? {1'b1, vg[3:2]} : vg[3:1]) :
                       ra == 2'd1 ? {1'b0, v[3:2]} :     // double height: top half
                       ra == 2'd2 ? {1'b1, v[3:2]} :     // bottom half
                       v[3:1];
    // VT640 text: the glyph bit, and whether this pixel shows text at all
    wire [3:0]  o2 = vtc[0] ? 4'd8 + 4'(vto) : 4'(vto);  // pixel in a double-width cell (15)
    wire [2:0]  vbit = ra != 2'd0 ? 3'((7'(o2) * 7'd8) / 7'd15) : vto;
    wire        vblank_ln = vln < 5'd2 || vln > 5'd17;
    wire        vt_x = h >= 10'd8 && h < 10'd608;
    wire        cursor_here = in_text && lrow == row && tcol == col && frame[5] &&
                              (vt640 ? !vblank_ln && vg[3:1] == 3'd7 : v[3:1] == 3'd7);
    assign g_vaddr = 15'(v) * 15'd40 + 15'(h[9:4]);

    logic [7:0] tq, pq, vl1, glyph;
    logic [2:0] line1;
    logic       text1, inv1, dp1, cur1, vis1, inv2, dp2, cur2, vis2, seg1, wide1, wide2, vsel1;
    logic [2:0] vbit1, vbit2;
    logic       vt1, vt2, vtx1, vtx2, vbl1, vbl2, gon1, gbit2;
    logic [6:0] segv1;

    // a 7-segment digit in an 8 x 8 cell (bit 0 = leftmost pixel): a on
    // row 0, f/b on rows 1-2, g on row 3, e/c on rows 4-5, d on row 6
    function automatic logic [7:0] seg_glyph(input logic [6:0] sg, input logic [2:0] ln);
        case (ln)
            3'd0:       seg_glyph = sg[0] ? 8'h1c : 8'h00;
            3'd1, 3'd2: seg_glyph = (sg[5] ? 8'h02 : 8'h00) | (sg[1] ? 8'h20 : 8'h00);
            3'd3:       seg_glyph = sg[6] ? 8'h1c : 8'h00;
            3'd4, 3'd5: seg_glyph = (sg[4] ? 8'h02 : 8'h00) | (sg[2] ? 8'h20 : 8'h00);
            3'd6:       seg_glyph = sg[3] ? 8'h1c : 8'h00;
            default:    seg_glyph = 8'h00;
        endcase
    endfunction
    logic [9:0] h1, h2;
    logic [9:0] v1, v2;
    always_ff @(posedge vclk) if (ce) begin
        tq <= tram[{prow, tcol}];                             // text RAM: one read port
        wide1 <= ra != 2'd0;
        pq <= p_ch;
        vl1 <= vpk_label_rom[vl_addr];                        // VPK label ROM (block RAM)
        vsel1 <= p_vlab;
        text1 <= in_text;
        inv1 <= in_panel && p_inv;
        dp1 <= in_panel && p_dp;
        seg1 <= in_panel && p_seg;
        segv1 <= seg_byte[6:0];
        cur1 <= cursor_here;
        vis1 <= (in_text || in_panel) && h < 10'd640;
        vt1 <= vt640 && in_text; vtx1 <= vt_x; vbl1 <= vblank_ln; vbit1 <= vbit;
        gon1 <= vt640 && !p_over && v < 10'd480 && h < 10'd640;
        line1 <= line;
        h1 <= h; v1 <= v;
        // stage 2
        glyph <= (seg1 ? seg_glyph(segv1, line1) : font8x8({(text1 ? tq[6:0] : vsel1 ? vl1[6:0] : pq[6:0]), line1})) |
                 (dp1 && line1 >= 3'd6 ? 8'h80 : 8'h00);       // decimal point
        inv2 <= inv1 || (text1 && tq[7]);                       // reverse video cell
        wide2 <= wide1;
        cur2 <= cur1;
        vis2 <= vis1;
        h2 <= h1; v2 <= v1;
        vt2 <= vt1; vtx2 <= vtx1; vbl2 <= vbl1; vbit2 <= vbit1;
        gbit2 <= gon1 && g_vq[h1[3:0]];
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
    wire       ptr_px = ptr_on && pdx < 10'd8 && pdy < 10'd8 && arow[pdx[2:0]] &&
                        (!vt640 || (panel_over && v2 >= 10'd384));

    wire vt_on = vtx2 && ((glyph[vbit2] && !vbl2) ^ inv2 ^ cur2);
    wire on = (vis2 && (vt2 ? vt_on : glyph[wide2 ? h2[3:1] : h2[2:0]] ^ inv2 ^ cur2)) || gbit2;
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
