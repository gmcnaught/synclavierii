// Self-checking test of hdl/core/panel_mouse.sv (verilator --binary):
// mouse packets -> pointer position (clamped to the screen) and panel
// button presses under the pointer (term_display.sv's button rows); with
// vpk set, VPK button presses/releases (PBN) and no ORK writes.
module panel_mouse_tb;
    logic        clk = 0, rst = 1;
    logic [24:0] ps2_mouse = '0;
    logic [9:0]  x;
    logic [8:0]  y;
    logic        moved, we, vpk = 0, vpk_we, vpk_down;
    logic [7:0]  vpk_pbn;
    logic [2:0]  index;
    logic [15:0] value;
    int          errors = 0;
    logic [18:0] got [$];
    logic [8:0]  vgot [$];

    panel_mouse dut (.*);

    always #5 clk = !clk;
    always @(posedge clk) if (we) got.push_back({index, value});
    always @(posedge clk) if (vpk_we) vgot.push_back({vpk_down, vpk_pbn});

    // one packet: buttons (bit 0 left), dx, dy (up positive)
    task automatic pkt(input logic left, input int dx, input int dy);
        logic [8:0] sx, sy;
        sx = 9'(dx); sy = 9'(dy);
        @(negedge clk);
        ps2_mouse = {!ps2_mouse[24], sy[7:0], sx[7:0], 2'b00, sy[8], sx[8], 3'b100, left};
        repeat (3) @(negedge clk);
    endtask

    task automatic check_pos(input int ex, input int ey);
        if (x != 10'(ex) || y != 9'(ey)) begin
            $display("FAIL: pointer (%0d, %0d), expected (%0d, %0d)", x, y, ex, ey);
            errors++;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst = 0;
        repeat (2) @(negedge clk);
        if (moved) begin $display("FAIL: moved before any packet"); errors++; end
        pkt(0, 100, -50);  check_pos(420, 290);         // starts at (320, 240); y down
        pkt(0, 255, 0); pkt(0, 255, 0); check_pos(639, 290);   // clamped right
        pkt(0, -256, 255); pkt(0, -256, 255); pkt(0, -256, 255); check_pos(0, 0);  // clamped left, top
        // to button row 6 (Bk/Tb: y 456-463), column 9 (x 360-399): PBN 105
        pkt(0, 255, -200); pkt(0, 105, -255); pkt(0, 0, -5);   // x 360, y 460
        check_pos(360, 460);
        pkt(1, 0, 0);                                     // press
        pkt(1, 30, 0);                                    // drag: still the same button
        pkt(0, 0, 0);                                     // release
        // a click outside the button rows does nothing
        pkt(0, 0, 200);                                   // y 260 (terminal)
        pkt(1, 0, 0); pkt(0, 0, 0);
        if (vgot.size() != 0) begin $display("FAIL: VPK writes in ORK mode %p", vgot); errors++; end
        // VPK panel: row 9 (y 472-479), column 13 (x 520-559) = PBN 157
        vpk = 1;
        pkt(0, 140, -215); check_pos(530, 475);
        pkt(1, 0, 0); pkt(1, 0, -2); pkt(0, 0, 0);        // press, drag, release
        // row 0 (y 400-407, above the ORK rows), column 1 = PBN 1
        pkt(0, -240, 73); pkt(0, -240, 0); check_pos(50, 404);
        pkt(1, 0, 0); pkt(0, 0, 0);
        // the terminal: nothing
        pkt(0, 0, 100); pkt(1, 0, 0); pkt(0, 0, 0);
        if (vgot.size() != 4 || vgot[0] != {1'b1, 8'd157} || vgot[1] != {1'b0, 8'd157} ||
            vgot[2] != {1'b1, 8'd1} || vgot[3] != {1'b0, 8'd1}) begin
            $display("FAIL: VPK writes %p", vgot);
            errors++;
        end
        if (!moved) begin $display("FAIL: moved not set"); errors++; end
        if (got.size() != 2 || got[0] != {3'd6, 16'h0200} || got[1] != {3'd6, 16'h0000}) begin
            $display("FAIL: writes %p", got);
            errors++;
        end
        if (errors != 0) $fatal(1);
        $display("panel_mouse OK");
        $finish;
    end
endmodule
