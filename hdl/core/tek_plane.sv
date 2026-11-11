// VT640 graphics plane (docs/devices/vt640-graphics-terminal.md; the
// reference is tools/vt100.py Terminal(vt640=True)): a Tektronix 4010
// subset drawn into a 640 x 480 x 1 bitmap, 40 16-bit words per screen
// row, row 0 = the top (VT640 y = 479); bit k of a word = pixel 16w + k.
//
//   GS vector mode (the next address moves), FS point mode, US alpha mode
//   (from vector/point), CAN back to text (`active` drops);
//   addresses HiY 040-077, LoY 0140-0177, HiX (040-077 after a LoY), LoX
//   0100-0137 (ends one); Tek -> pixel: x = (xt*640+512)>>10,
//   y = (min(yt,779)*630+640)>>10; vector: a line from the last point once
//   the pen is down (Bresenham, both ends); point: one pixel;
//   ESC FF clear, pen up; ESC / n d data level (0 set, 1 clear, 2 XOR);
//   ESC | c c and ESC \ c skipped; other ESC c ignored (sizes: one size);
//   alpha: printable -> 8 x 14 cell, lower-left at the position, the 5 x 7
//   glyph (font5x7.svh) on columns 1-5, cell lines 2-12 from the top (line
//   l = 12 - gl from the bottom: font row 6 - l*2/3), x += 8; BS x -= 8, CR x = 0,
//   LF y -= 14.
//   ESC " p ; y ; n c   read back (M21, SYN-5.3's screen hardcopy): n (at
//   most 128) 5-pixel groups of line y (0 = bottom) from x = 0, coded as
//   tools/vt100.py readback_reply (run lengths, then CR); the reply is made
//   at once into a 512-byte buffer and, with rb_en, sent out on rb_valid /
//   rb_data (one byte a clock, into the terminal's input) 2 ms of simulated
//   time (tick_ns) later, as sim/boot.py READBACK_NS; other finals ignored.
// A byte is taken (in_valid && ready) only when the plane is idle; a pixel
// costs 2 clocks (read, then write the word back), a clear 19200 clocks, a
// read-back about 6 clocks a group.
// Video reads the bitmap on vclk (v_addr -> v_q a clock later).
module tek_plane (
    input  logic        clk,
    input  logic        rst,
    input  logic        in_valid,
    input  logic [7:0]  in_data,
    output logic        ready,
    output logic        active,         // in a graphics mode (bytes belong here)

    input  logic        tick,           // simulated time (read-back delay)
    input  logic [9:0]  tick_ns,
    input  logic        rb_en,          // answer read-back requests
    output logic        rb_valid,       // read-back reply bytes, for the terminal's input
    output logic [7:0]  rb_data,

    input  logic        vclk,
    input  logic        v_ce,           // the video's pixel enable: read on it
    input  logic [14:0] v_addr,         // word: row * 40 + x / 16
    output logic [15:0] v_q
);
    `include "font5x7.svh"

    localparam int WORDS = 640 * 480 / 16;

    // ------------------------------------------------------------ bitmap
    logic [15:0] mem [WORDS];
    logic [14:0] a_addr;
    logic        a_we;
    logic [15:0] a_d, a_q;
    always_ff @(posedge clk) begin
        if (a_we) mem[a_addr] <= a_d;
        a_q <= mem[a_addr];
    end
    always_ff @(posedge vclk) if (v_ce) v_q <= mem[v_addr];

    // ------------------------------------------------------------ decoder
    localparam logic [1:0] G_NONE = 2'd0, G_VEC = 2'd1, G_PNT = 2'd2, G_ALPHA = 2'd3;
    localparam logic [2:0] E_NO = 3'd0, E_ESC = 3'd1, E_SLASH = 3'd2, E_SKIP2 = 3'd3, E_SKIP1 = 3'd4,
                           E_RB = 3'd5;
    logic [1:0]  gmode;
    logic [2:0]  gesc;
    logic [3:0]  num;
    logic        pen, after_loy;
    logic [4:0]  hiy, loy, hix;
    logic [1:0]  level;
    logic signed [11:0] gx, gy;        // graphics position (may leave the screen in alpha)
    assign active = gmode != G_NONE;

    wire [7:0] c = in_data & 8'h7f;
    // the address completed by a LoX byte c
    wire [9:0]  xt = {hix, c[4:0]};
    wire [9:0]  yt = {hiy, loy} > 10'd779 ? 10'd779 : {hiy, loy};
    wire [19:0] xs = 20'(xt) * 20'd640 + 20'd512;
    wire [19:0] ys = 20'(yt) * 20'd630 + 20'd640;
    wire [9:0]  nx = xs[19:10];
    wire [9:0]  ny = ys[19:10];

    // ------------------------------------------------------ pixel engine
    localparam logic [2:0] T_IDLE = 3'd0, T_CLEAR = 3'd1, T_LINE = 3'd2, T_GLYPH = 3'd3,
                           T_RD = 3'd4, T_WR = 3'd5, T_RB = 3'd6, T_RBEMIT = 3'd7;
    logic [2:0]  t, t_ret;              // state; where T_WR returns to
    // line
    logic signed [11:0] lx, ly, lx1, ly1, ldx, ldy, lerr;
    logic        lsx, lsy;
    // glyph: cell line gl (0-13 from the top), column gc
    logic [3:0]  gl;
    logic [2:0]  gc;
    logic [6:0]  gch;
    logic signed [11:0] cx, cy;         // the cell's lower-left corner
    // the pixel being written
    logic signed [11:0] px, py;
    logic [3:0]  pbit;

    assign ready = t == T_IDLE;

    // ------------------------------------------------- read-back (M21)
    logic [1:0]  rb_i;                  // parameter being read
    logic [9:0]  rb_p [3];              // the parameters (saturating)
    logic [8:0]  rb_row;                // screen row (0 = top) of the line
    logic        rb_blank;              // line off the screen
    logic [7:0]  rb_n;                  // groups to send
    logic [7:0]  rb_k;                  // groups done
    logic [9:0]  rb_x;                  // next pixel
    logic [2:0]  rb_b;                  // pixels of this group so far
    logic [4:0]  rb_g;                  // this group's value so far
    logic [5:0]  rb_w;                  // word index in wq
    logic        rb_wv;                 // wq holds word rb_w
    logic [15:0] wq;
    logic [4:0]  run_v;                 // the run being counted
    logic [5:0]  run_n;
    logic [7:0]  em [3];                // bytes still to emit for a finished run
    logic [1:0]  em_n;
    logic        rb_last;               // after the emission: the trailer
    logic        rb_fin;                // the trailer is out: done
    logic [1:0]  rb_ph;                 // word fetch: 1 address out, 2 data in
    wire         rb_pix = !rb_blank && rb_x < 10'd640 && wq[rb_x[3:0]];
    wire  [4:0]  rb_v = {rb_g[3:0], rb_pix};
    // reply buffer and its sender
    logic [7:0]  rbuf [512];
    logic [8:0]  rb_wp, rb_len, rb_sp;
    logic        rb_bwe;
    logic [7:0]  rb_bd;
    logic        rb_go, rb_pend, rb_sending;
    logic signed [31:0] rb_due;
    always_ff @(posedge clk) begin
        if (rb_bwe) rbuf[rb_wp] <= rb_bd;
        rb_data <= rbuf[rb_sp];
    end
    always_ff @(posedge clk) begin
        rb_valid <= 1'b0;
        if (rst) begin
            rb_pend <= 1'b0; rb_sending <= 1'b0;
        end else if (rb_go) begin                   // a reply is made: send it 2 ms on
            rb_pend <= 1'b1; rb_due <= 32'sd2_000_000; rb_sending <= 1'b0;
        end else if (rb_pend && rb_due > 0) begin
            if (tick) rb_due <= rb_due - 32'(tick_ns);
        end else if (rb_pend && rb_en) begin
            rb_pend <= 1'b0; rb_sending <= 1'b1; rb_sp <= '0;
        end else if (rb_sending) begin              // rbuf[rb_sp] is on rb_data next clock
            rb_valid <= 1'b1;
            if (rb_sp + 9'd1 == rb_len) rb_sending <= 1'b0;
            rb_sp <= rb_sp + 9'd1;
        end
    end
    // a run's bytes (tools/vt100.py readback_reply)
    task automatic finish_run(input logic [4:0] v, input logic [5:0] n);
        if (v == 5'd0) begin em[0] <= 8'o44; em[1] <= {2'b01, n}; em_n <= 2'd2; end
        else if (v == 5'd31) begin em[0] <= 8'o45; em[1] <= {2'b01, n}; em_n <= 2'd2; end
        else if (n >= 6'd3) begin em[0] <= 8'o46; em[1] <= {3'b010, v}; em[2] <= {2'b01, n}; em_n <= 2'd3; end
        else begin em[0] <= {3'b010, v}; em[1] <= {3'b010, v}; em_n <= 2'(n); end
    endtask

    // pixel (x, y) -> word address and bit; on screen?
    function automatic logic [14:0] waddr(input logic signed [11:0] x, input logic signed [11:0] y);
        logic [9:0] sr;
        sr = 10'(12'sd479 - y);
        waddr = 15'(sr) * 15'd40 + 15'(x[9:4]);
    endfunction
    function automatic logic onscreen(input logic signed [11:0] x, input logic signed [11:0] y);
        onscreen = x >= 0 && x < 640 && y >= 0 && y < 480;
    endfunction

    // the glyph pixel at (gl, gc): cell lines 2-12 from the top (line 12 - gl
    // from the bottom, font row 6 - line*2/3), columns 1-5 (font bit gc - 1)
    wire [3:0] g_ln  = 4'd12 - gl;
    wire [2:0] g_row = 3'd6 - 3'((5'(g_ln) * 5'd2) / 5'd3);
    wire [4:0] g_bits = font5x7({gch, g_row});
    wire [2:0] g_col = gc - 3'd1;
    wire       g_on  = gl >= 4'd2 && gl <= 4'd12 && gc >= 3'd1 && gc <= 3'd5 && g_bits[g_col];
    wire signed [11:0] g_x = cx + 12'(gc);
    wire signed [11:0] g_y = cy + 12'sd13 - 12'(gl);

    // Bresenham: the next point
    wire signed [12:0] e2 = {lerr, 1'b0};

    task automatic plot(input logic signed [11:0] x, input logic signed [11:0] y,
                        input logic [2:0] ret);
        if (onscreen(x, y)) begin
            a_addr <= waddr(x, y);
            pbit <= x[3:0];
            t <= T_RD;
            t_ret <= ret;
        end else t <= ret;
    endtask

    always_ff @(posedge clk) begin
        a_we <= 1'b0;
        rb_bwe <= 1'b0; rb_go <= 1'b0;
        if (rb_bwe) rb_wp <= rb_wp + 9'd1;
        if (rst) begin
            rb_len <= '0; rb_fin <= 1'b0;
            gmode <= G_NONE; gesc <= E_NO; pen <= 1'b0; after_loy <= 1'b0;
            level <= 2'd0; gx <= '0; gy <= '0; hiy <= '0; loy <= '0; hix <= '0;
            t <= T_CLEAR; a_addr <= '0;
        end else case (t)
        T_CLEAR: begin
            a_we <= 1'b1; a_d <= '0;
            if (a_we) begin
                if (a_addr == 15'(WORDS - 1)) begin t <= T_IDLE; a_we <= 1'b0; end
                else a_addr <= a_addr + 15'd1;
            end
        end
        T_RD: t <= T_WR;                                  // a_q valid next clock
        T_WR: begin
            a_we <= 1'b1;
            case (level)
                2'd1:    a_d <= a_q & ~(16'd1 << pbit);
                2'd2:    a_d <= a_q ^ (16'd1 << pbit);
                default: a_d <= a_q | (16'd1 << pbit);
            endcase
            t <= t_ret;
        end
        T_LINE: begin                                     // plot (lx, ly), then step
            if (lx == lx1 && ly == ly1) plot(lx, ly, T_IDLE);
            else begin
                plot(lx, ly, T_LINE);
                if (e2 >= 13'(ldy)) begin lerr <= lerr + ldy + ((e2 <= 13'(ldx)) ? ldx : 12'sd0);
                                          lx <= lsx ? lx - 12'sd1 : lx + 12'sd1; end
                else if (e2 <= 13'(ldx)) lerr <= lerr + ldx;
                if (e2 <= 13'(ldx)) ly <= lsy ? ly - 12'sd1 : ly + 12'sd1;
            end
        end
        T_RB: begin                                       // the next pixel of the line
            if (rb_k == rb_n) begin                       // all groups: the last run, then CR
                if (rb_n != 8'd0) finish_run(run_v, run_n);
                rb_last <= 1'b1;
                t <= T_RBEMIT;
            end else if (rb_ph == 2'd1) rb_ph <= 2'd2;     // a_q is being read
            else if (rb_ph == 2'd2) begin                 // the word holding pixel rb_x
                wq <= a_q; rb_w <= rb_x[9:4]; rb_wv <= 1'b1; rb_ph <= 2'd0;
            end else if (!rb_blank && rb_x < 10'd640 && !(rb_wv && rb_w == rb_x[9:4])) begin
                a_addr <= 15'(rb_row) * 15'd40 + 15'(rb_x[9:4]);
                rb_ph <= 2'd1;
            end else begin                                // take pixel rb_x
                rb_x <= rb_x + 10'd1;
                if (rb_b != 3'd4) begin
                    rb_g <= {rb_g[3:0], rb_pix}; rb_b <= rb_b + 3'd1;
                end else begin                            // a group: count it into the run
                    rb_b <= '0; rb_k <= rb_k + 8'd1;
                    if (rb_k == 8'd0) begin run_v <= rb_v; run_n <= 6'd1; end
                    else if (rb_v == run_v && run_n != 6'd63) run_n <= run_n + 6'd1;
                    else begin
                        finish_run(run_v, run_n);
                        run_v <= rb_v; run_n <= 6'd1;
                        t <= T_RBEMIT;
                    end
                end
            end
        end
        T_RBEMIT: begin                                   // a run's bytes into the reply
            if (em_n != 2'd0) begin
                rb_bwe <= 1'b1; rb_bd <= em[0]; em[0] <= em[1]; em[1] <= em[2]; em_n <= em_n - 2'd1;
            end else if (rb_last) begin
                rb_bwe <= 1'b1; rb_bd <= 8'o15; rb_last <= 1'b0; rb_fin <= 1'b1;
            end else if (rb_fin) begin                    // the reply is made
                rb_fin <= 1'b0;
                rb_len <= rb_wp + {8'd0, rb_bwe}; rb_go <= 1'b1;
                t <= T_IDLE;
            end else t <= T_RB;
        end
        T_GLYPH: begin                                    // one cell position per visit
            if (g_on) plot(g_x, g_y, T_GLYPH);
            if (gc == 3'd7) begin
                gc <= 3'd0;
                if (gl == 4'd13) begin
                    if (!g_on || !onscreen(g_x, g_y)) t <= T_IDLE;
                    else t_ret <= T_IDLE;
                end
                gl <= gl + 4'd1;
            end else gc <= gc + 3'd1;
        end
        default: if (in_valid) begin                      // T_IDLE: a byte
            if (gesc != E_NO) begin
                case (gesc)
                    E_ESC: begin
                        gesc <= E_NO;
                        if (c == 8'h0c) begin pen <= 1'b0; t <= T_CLEAR; a_addr <= '0; end
                        else if (c == 8'h2f) begin gesc <= E_SLASH; num <= '0; end
                        else if (c == 8'h7c) gesc <= E_SKIP2;
                        else if (c == 8'h5c) gesc <= E_SKIP1;
                        else if (c == 8'h22) begin
                            gesc <= E_RB; rb_i <= '0;
                            rb_p[0] <= '0; rb_p[1] <= '0; rb_p[2] <= '0;
                        end
                    end
                    E_SLASH:
                        if (c >= 8'h30 && c <= 8'h39)
                            num <= 7'(num) * 7'd10 + 7'(c[3:0]) > 7'd9 ? 4'd9 : 4'(7'(num) * 7'd10 + 7'(c[3:0]));
                        else if (c == 8'h64) begin level <= num <= 4'd2 ? num[1:0] : 2'd0; gesc <= E_NO; end
                        else if (c == 8'h3b) num <= '0;
                        else gesc <= E_NO;
                    E_SKIP2: gesc <= E_SKIP1;
                    E_RB:
                        if (c >= 8'h30 && c <= 8'h39)
                            rb_p[rb_i] <= 14'(rb_p[rb_i]) * 14'd10 + 14'(c[3:0]) > 14'd1023 ? 10'd1023
                                          : 10'(14'(rb_p[rb_i]) * 14'd10 + 14'(c[3:0]));
                        else if (c == 8'h3b) begin if (rb_i != 2'd2) rb_i <= rb_i + 2'd1; end
                        else begin
                            gesc <= E_NO;
                            if (c == 8'h63 && rb_i == 2'd2) begin      // 'c': read line y back
                                rb_blank <= rb_p[1] > 10'd479;
                                rb_row <= 9'(10'd479 - rb_p[1]);
                                rb_n <= rb_p[2] > 10'd128 ? 8'd128 : rb_p[2][7:0];
                                rb_k <= '0; rb_x <= '0; rb_b <= '0; rb_g <= '0;
                                rb_wv <= 1'b0; rb_ph <= '0; rb_wp <= '0; rb_len <= '0;
                                em_n <= '0; rb_last <= 1'b0; rb_fin <= 1'b0;
                                t <= T_RB;
                            end
                        end
                    default: gesc <= E_NO;
                endcase
            end else if (c == 8'h1d) begin gmode <= G_VEC; pen <= 1'b0; after_loy <= 1'b0; end
            else if (c == 8'h1c) begin gmode <= G_PNT; after_loy <= 1'b0; end
            else if (c == 8'h18) gmode <= G_NONE;
            else if (c == 8'h1b) gesc <= E_ESC;
            else if (c == 8'h1f) begin if (gmode == G_VEC || gmode == G_PNT) gmode <= G_ALPHA; end
            else if (gmode == G_ALPHA) begin
                if (c >= 8'h20 && c <= 8'h7e) begin
                    gch <= c[6:0]; gl <= '0; gc <= '0; cx <= gx; cy <= gy;
                    gx <= gx + 12'sd8;
                    t <= T_GLYPH;
                end else if (c == 8'h08) gx <= gx - 12'sd8;
                else if (c == 8'h0d) gx <= '0;
                else if (c == 8'h0a) gy <= gy - 12'sd14;
            end else if (c >= 8'h20) begin                // an address byte
                if (c >= 8'h60) begin loy <= c[4:0]; after_loy <= 1'b1; end
                else if (c < 8'h40) begin
                    if (after_loy) hix <= c[4:0]; else hiy <= c[4:0];
                    after_loy <= 1'b0;
                end else begin                            // LoX
                    after_loy <= 1'b0;
                    gx <= 12'(nx); gy <= 12'(ny);
                    if (gmode == G_VEC) begin
                        if (pen) begin
                            lx <= gx; ly <= gy; lx1 <= 12'(nx); ly1 <= 12'(ny);
                            ldx <= 12'(nx) >= gx ? 12'(nx) - gx : gx - 12'(nx);
                            ldy <= -(12'(ny) >= gy ? 12'(ny) - gy : gy - 12'(ny));
                            lerr <= (12'(nx) >= gx ? 12'(nx) - gx : gx - 12'(nx))
                                  - (12'(ny) >= gy ? 12'(ny) - gy : gy - 12'(ny));
                            lsx <= !(gx < 12'(nx)); lsy <= !(gy < 12'(ny));
                            t <= T_LINE;
                        end
                        pen <= 1'b1;
                    end else plot(12'(nx), 12'(ny), T_IDLE);
                end
            end
        end
        endcase
    end
endmodule
