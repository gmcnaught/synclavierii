// hdl/core/term_display.sv at one clock per pixel (the MiSTer setting),
// with panel lights, a display value and the pointer set; writes one frame
// as a PGM (argument +frame=PATH) for tests/hdl/test_board.py to read back.
//   lights: panel word 6 = 0x0201 (Bk1 and Tb2 lit), word 0 bit 15 (HSus)
//   display: "12.34" (7-segment codes as NED's DIGITS table; DP on digit 2),
//            units 0x0004
//   pointer at (600, 100)
//   terminal: "HELLO" then CR LF and "WORLD", or the bytes of +input=FILE;
//   prints the keypad mode at the end ("keypad_app N")
//   +vpk: the VPK panel: display " SYNCLAVIER 5.3 " / "40 VOICES 36M  ",
//         character 31 = 0x01 (shown as a space); PBN 33 (Stop) on, PBN 159
//         (VClr) state 3, PBN 108 (Tb5) blinking; the frame is one with the
//         blink phase off and +frame2=PATH one with it on
module term_display_tb;
    logic        clk = 0, rst = 1;
    logic        in_valid = 0;
    logic [7:0]  in_data = '0;
    logic [15:0] lights [8];
    logic [15:0] display [3];
    logic        vpk = 0;
    logic [1:0]  vpk_lights [160];
    logic [7:0]  vpk_chars [32];
    logic        ce_pix, hs, vs, hblank, vblank;
    logic [7:0]  r, g, b, peek_data;
    logic [4:0]  top_row;
    logic        keypad_app;

    term_display #(.CE_DIV(1)) dut (
        .clk, .rst, .vclk(clk), .in_valid, .in_data, .color(2'd0),
        .lights, .display, .ptr_on(1'b1), .ptr_x(10'd600), .ptr_y(9'd100),
        .lag_us(32'h0001_2a3f), .underruns(16'h0002), .overruns(16'h0000),
        .midi_count(16'h0123), .midi_last(8'hf8), .midi_errs(16'h0000), .midi_alt(1'b1),
        .vpk, .vpk_lights, .vpk_chars,
        .ce_pix, .r, .g, .b, .hs, .vs, .hblank, .vblank,
        .peek_addr(12'd0), .peek_data, .top_row, .keypad_app
    );

    always #5 clk = !clk;

    task automatic put(input string s);
        for (int i = 0; i < s.len(); i++) begin
            @(negedge clk); in_valid = 1; in_data = s[i];
        end
        @(negedge clk); in_valid = 0;
    endtask

    // the next 640 x 480 visible pixels from the start of a frame whose
    // blink phase (frame counter bit 5) is `phase`, to a PGM
    task automatic capture(input string p, input logic phase);
        int f, cnt;
        forever begin
            while (!vblank) @(negedge clk);
            while (vblank) @(negedge clk);
            if (dut.frame[5] == phase) break;
        end
        f = $fopen(p, "wb");
        $fwrite(f, "P5\n640 480\n255\n");
        cnt = 0;
        while (cnt < 640 * 480) begin
            if (ce_pix && !hblank && !vblank) begin
                $fwrite(f, "%c", g);
                cnt++;
            end
            @(negedge clk);
        end
        $fclose(f);
    endtask

    string path, path2, inpath, vtext;
    int    fd, n, fin, ch;
    initial begin
        for (int i = 0; i < 8; i++) lights[i] = '0;
        lights[6] = 16'h0201;
        lights[0] = 16'h8000;
        display[1] = {8'o006, 8'o133 | 8'o200};        // "1", "2."
        display[0] = {8'o117, 8'o146};                 // "3", "4"
        display[2] = 16'h0004;
        vpk = $test$plusargs("vpk");
        vtext = " SYNCLAVIER 5.3 40 VOICES 36M  ";
        for (int i = 0; i < 32; i++) vpk_chars[i] = i < 31 ? vtext[i] : 8'h01;
        for (int i = 0; i < 160; i++) vpk_lights[i] = 2'd0;
        vpk_lights[(33 & 15) + 144 - (33 & ~15)] = 2'd1;
        vpk_lights[(159 & 15) + 144 - (159 & ~15)] = 2'd3;
        vpk_lights[(108 & 15) + 144 - (108 & ~15)] = 2'd2;
        if (!$value$plusargs("frame=%s", path)) path = "frame.pgm";
        repeat (4) @(negedge clk);
        rst = 0;
        repeat (2100) @(negedge clk);                   // screen clear
        if ($value$plusargs("input=%s", inpath)) begin
            fin = $fopen(inpath, "rb");
            while ((ch = $fgetc(fin)) != -1) begin
                @(negedge clk); in_valid = 1; in_data = 8'(ch);
                @(negedge clk); in_valid = 0;
                repeat (100) @(negedge clk);              // erases take up to 1920 clocks:
                while (dut.wstate != 0) @(negedge clk);   // keep the 64-byte FIFO from filling
            end
            $fclose(fin);
            repeat (2100) @(negedge clk);
        end else put("HELLO\r\nWORLD");
        // to the start of a frame, then 640 x 480 visible pixels
        if (vpk) begin
            capture(path, 1'b0);
            if ($value$plusargs("frame2=%s", path2)) capture(path2, 1'b1);
        end else begin
            while (!vblank) @(negedge clk);
            while (vblank) @(negedge clk);
            fd = $fopen(path, "wb");
            $fwrite(fd, "P5\n640 480\n255\n");
            n = 0;
            while (n < 640 * 480) begin
                if (ce_pix && !hblank && !vblank) begin
                    $fwrite(fd, "%c", g);
                    n++;
                end
                @(negedge clk);
            end
            $fclose(fd);
        end
        $display("keypad_app %0d", keypad_app);
        $display("term_display OK");
        $finish;
    end
endmodule
