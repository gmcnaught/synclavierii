// Self-checking test of hdl/core/crt_adjust.sv (verilator --binary): a
// 640 x 480 raster whose pixels encode their own (x, y), through Off and
// several H-Size / H-Position / V-Shift settings. Measured on the output:
// each active pixel shows input pixel floor((320 k + 32 x) / (32 + k)) of
// the same line (black outside the line), 640 x 480 active pixels a frame,
// the HSync rise at x = 656 - 4 hpos and the VSync rise on line 490 - vpos
// (positions counted from the output's own blanking).
module crt_adjust_tb;
    logic clk = 0;
    always #5 clk = !clk;

    logic              enable = 0;
    logic signed [4:0] hsize = 0;
    logic signed [3:0] hpos = 0, vpos = 0;
    logic [9:0] h = 0, v = 0;
    logic [7:0] r_in, g_in, b_in, r_out, g_out, b_out;
    logic       hs_in, vs_in, hblank_in, vblank_in, hs_out, vs_out, hblank_out, vblank_out;
    int         errors = 0;

    function automatic logic [23:0] enc(input int x, input int y);
        enc = {x[7:0], x[9:8], y[5:0], 5'd1, y[8:6]};
    endfunction

    // the input raster, as term_display makes it (all registered from h, v)
    always_ff @(posedge clk) begin
        if (h == 799) begin h <= 0; v <= v == 524 ? 10'd0 : v + 10'd1; end
        else h <= h + 1;
        hblank_in <= h >= 640;
        vblank_in <= v >= 480;
        hs_in <= h >= 656 && h < 752;
        vs_in <= v >= 490 && v < 492;
        {r_in, g_in, b_in} <= (h < 640 && v < 480) ? enc(h, v) : 24'h5a5a5a;
    end

    crt_adjust dut (.clk, .ce(1'b1), .*);

    // the output measured from its own blanking
    // (one process writes the counts: the test resets them through `clear`)
    int  ox = 0, oy = 0, de_n = 0, hs_x = -1, vs_y = -1, checking = 0, clear = 0;
    logic hb_q = 1, vb_q = 1, hs_q = 0, vs_q = 0;
    always @(posedge clk) begin
        automatic int x = (hb_q && !hblank_out) ? 0 : ox;
        automatic int y = !(hb_q && !hblank_out) ? oy : (vb_q && !vblank_out) ? 0 : oy + 1;
        automatic int a = 32 + hsize;
        automatic int num = 320 * hsize + 32 * x;
        automatic int src = (num >= 0) ? num / a : -((-num + a - 1) / a);
        automatic logic [23:0] want = (src >= 0 && src < 640) ? enc(src, y) : 24'd0;
        automatic logic [23:0] got = {r_out, g_out, b_out};
        if (clear) begin de_n = 0; hs_x = -1; vs_y = -1; end
        if (checking) begin
            if (!hblank_out && !vblank_out) begin
                de_n = de_n + 1;
                if (got !== (enable ? want : enc(x, y))) begin
                    if (errors < 10) $display("pixel (%0d,%0d) k=%0d: got %06x want %06x", x, y, hsize, got,
                                              enable ? want : enc(x, y));
                    errors++;
                end
            end else if (enable && got !== 24'd0) begin
                if (errors < 10) $display("blank (%0d,%0d): %06x", x, y, got);
                errors++;
            end
            if (hs_out && !hs_q) hs_x = x;
            if (vs_out && !vs_q) vs_y = y;
        end
        hb_q = hblank_out; vb_q = vblank_out; hs_q = hs_out; vs_q = vs_out;
        ox = x + 1; oy = y;
    end

    // passthrough when off: the outputs are the inputs, every clock
    always @(negedge clk) if (!enable && {r_out, g_out, b_out, hs_out, vs_out, hblank_out, vblank_out} !==
                               {r_in, g_in, b_in, hs_in, vs_in, hblank_in, vblank_in}) begin
        if (errors < 10) $display("passthrough differs at h=%0d v=%0d", h, v);
        errors++;
    end

    // frame boundaries in the input's vertical blanking: one window holds
    // exactly one output frame with or without the output's line delay
    task automatic frames_at_top(input int n);
        repeat (n) begin
            @(posedge clk iff (h == 0 && v == 500));
        end
    endtask

    task automatic check(input logic en, input int k, input int hp, input int vp);
        @(negedge clk);
        enable = en; hsize = k; hpos = hp; vpos = vp;
        checking = 0;
        frames_at_top(3);                 // lock, latch H-Size, settle
        @(negedge clk);
        clear = 1; @(negedge clk); clear = 0; checking = 1;
        frames_at_top(1);
        @(negedge clk);
        checking = 0;
        if (de_n != 640 * 480) begin $display("en=%0d k=%0d: %0d active pixels", en, k, de_n); errors++; end
        if (hs_x != 656 - 4 * (en ? hp : 0)) begin $display("hpos %0d: HSync at x %0d", hp, hs_x); errors++; end
        if (vs_y != 490 - (en ? vp : 0)) begin $display("vpos %0d: VSync on line %0d", vp, vs_y); errors++; end
        $display("  en=%0d hsize=%0d hpos=%0d vpos=%0d: HSync x %0d, VSync line %0d", en, k, hp, vp, hs_x, vs_y);
    endtask

    initial begin
        check(0, 0, 0, 0);
        check(1, 0, 0, 0);
        check(1, 0, 7, 0);
        check(1, 0, -8, 0);
        check(1, 0, 0, 7);
        check(1, 0, 0, -8);
        check(1, 10, 0, 0);
        check(1, -12, 3, -2);
        check(1, -1, 0, 0);
        check(1, 4, -3, 5);
        check(0, 4, -3, 5);
        if (errors == 0) $display("crt_adjust OK");
        else $display("crt_adjust: %0d errors", errors);
        $finish;
    end
endmodule
