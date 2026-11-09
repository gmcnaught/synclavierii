// Self-checking test of hdl/core/midi_card_feed.sv (with midi_in.sv in
// front) and midi_uart_tx (hdl/dev/dev_midi.sv), verilator --binary.
// 1 MHz clock, 31250 baud (32 clocks a bit).
module midi_card_tb;
    localparam longint HZ = 1_000_000;
    logic        clk = 0, rst = 1, rxd = 1, vpk = 0;
    logic        host_we, host_panel;
    logic [2:0]  host_index;
    logic [15:0] host_value;
    logic        byte_valid, frame_err, alt;
    logic [7:0]  byte_data;
    logic        msg_valid;
    logic [2:0]  msg_kind;
    logic [3:0]  msg_chan;
    logic [6:0]  msg_m1, msg_m2;
    logic        panel, out_valid;
    logic [7:0]  out_data;

    midi_in #(.CLK_HZ(HZ)) rx (.*);
    midi_card_feed feed (.clk, .rst, .vpk, .msg_valid, .msg_kind, .msg_chan, .msg_m1, .msg_m2,
                         .byte_valid, .byte_data, .panel, .out_valid, .out_data);

    always #5 clk = !clk;

    byte got [$];
    int  panels = 0;
    always @(posedge clk) begin
        if (out_valid) got.push_back(out_data);
        if (msg_valid && panel) panels++;
    end

    task automatic send(input logic [7:0] b);
        rxd = 0; repeat (32) @(negedge clk);
        for (int i = 0; i < 8; i++) begin rxd = b[i]; repeat (32) @(negedge clk); end
        rxd = 1; repeat (40) @(negedge clk);
    endtask

    int errors = 0;
    task automatic expect_bytes(input string what, input byte want [$], input int want_panels);
        repeat (20) @(negedge clk);
        if (got.size() != want.size()) begin
            $display("FAIL %s: %0d bytes, expected %0d", what, got.size(), want.size());
            errors++;
        end
        for (int i = 0; i < want.size() && i < got.size(); i++)
            if (got[i] != want[i]) begin
                $display("FAIL %s: byte %0d = %02h, expected %02h", what, i, got[i], want[i]);
                errors++;
            end
        if (panels != want_panels) begin
            $display("FAIL %s: %0d panel messages, expected %0d", what, panels, want_panels);
            errors++;
        end
        got.delete(); panels = 0;
    endtask

    // MIDI out: midi_uart_tx into a receiver at the same speed
    logic       t_valid = 0, t_ready, txd, l_alt = 0;
    logic [7:0] t_data = 0;
    logic       lv_std, le_std, lv_alt, le_alt;
    logic [7:0] ld_std, ld_alt;
    midi_uart_tx #(.CLK_HZ(HZ)) tx (.clk, .rst, .alt(l_alt), .valid(t_valid), .data(t_data),
                                    .ready(t_ready), .txd);
    midi_uart_rx #(.CLK_HZ(HZ), .BAUD(31_250)) l_std (.clk, .rst, .rxd(txd), .valid(lv_std),
                                                      .data(ld_std), .ferr(le_std));
    midi_uart_rx #(.CLK_HZ(HZ), .BAUD(9_600)) l_alt_rx (.clk, .rst, .rxd(txd), .valid(lv_alt),
                                                        .data(ld_alt), .ferr(le_alt));
    byte loop [$];
    int  ferrs = 0;
    always @(posedge clk) begin
        if (!l_alt && lv_std) loop.push_back(ld_std);
        if (l_alt && lv_alt) loop.push_back(ld_alt);
        if ((!l_alt && le_std) || (l_alt && le_alt)) ferrs++;
    end
    task automatic transmit(input byte bs [$]);
        foreach (bs[i]) begin
            @(negedge clk);
            while (!t_ready) @(negedge clk);
            t_valid = 1; t_data = bs[i];
            @(negedge clk);
            t_valid = 0;
        end
        repeat (l_alt ? 1200 : 400) @(negedge clk);
    endtask

    initial begin
        byte none [$];
        repeat (4) @(negedge clk);
        rst = 0;
        repeat (40) @(negedge clk);

        // ORK: note on/off (running status, velocity 0), CC, bend, program,
        // channel pressure, key pressure; channel 16 notes are panel buttons
        send(8'h91); send(8'd60); send(8'd100); send(8'd60); send(8'd0);
        expect_bytes("notes", '{8'h91, 8'd60, 8'd100, 8'h81, 8'd60, 8'd0}, 0);
        send(8'hb0); send(8'd1); send(8'd64); send(8'he0); send(8'd5); send(8'd127);
        send(8'hc2); send(8'd9); send(8'hd3); send(8'd77); send(8'ha4); send(8'd61); send(8'd50);
        expect_bytes("controls", '{8'hb0, 8'd1, 8'd64, 8'he0, 8'd5, 8'd127, 8'hc2, 8'd9,
                                   8'hd3, 8'd77, 8'ha4, 8'd61, 8'd50}, 0);
        send(8'h9f); send(8'd32); send(8'd127); send(8'h8f); send(8'd32); send(8'd0);
        expect_bytes("ch16 panel", none, 2);
        // real time passes (also inside a message); FE, SysEx, system common do not
        send(8'h90); send(8'd62); send(8'hf8); send(8'd90);
        send(8'hfa); send(8'hfe); send(8'hfc); send(8'hfb);
        send(8'hf0); send(8'h43); send(8'h10); send(8'hf7); send(8'hf2); send(8'd1); send(8'd2);
        expect_bytes("real time", '{8'hf8, 8'h90, 8'd62, 8'd90, 8'hfa, 8'hfc, 8'hfb}, 0);
        // ORK: pads and pots go to the card
        send(8'h99); send(8'd36); send(8'd80); send(8'hb0); send(8'd21); send(8'd70);
        expect_bytes("ork pads", '{8'h99, 8'd36, 8'd80, 8'hb0, 8'd21, 8'd70}, 0);

        // VPK: pads, pots, channel 15 and 16 notes are panel; other notes pass
        vpk = 1;
        send(8'h99); send(8'd36); send(8'd80); send(8'd52); send(8'd80);
        send(8'hb0); send(8'd21); send(8'd70); send(8'd28); send(8'd1); send(8'd29); send(8'd2);
        send(8'h9e); send(8'd3); send(8'd127); send(8'h9f); send(8'd4); send(8'd127);
        send(8'h90); send(8'd36); send(8'd80);
        expect_bytes("vpk", '{8'h99, 8'd52, 8'd80, 8'hb0, 8'd29, 8'd2, 8'h90, 8'd36, 8'd80}, 5);

        // MIDI out at 31250, then at 9600
        transmit('{8'hb0, 8'h7b, 8'h00, 8'h55, 8'haa, 8'hff});
        if (loop.size() != 6 || loop[0] != 8'hb0 || loop[1] != 8'h7b || loop[3] != 8'h55
            || loop[4] != 8'haa || loop[5] != 8'hff || ferrs != 0) begin
            $display("FAIL tx 31250: %p ferrs %0d", loop, ferrs); errors++;
        end
        loop.delete();
        l_alt = 1;
        repeat (3000) @(negedge clk);           // the 9600 receiver resyncs
        loop.delete(); ferrs = 0;
        transmit('{8'h90, 8'h3c, 8'h40});
        if (loop.size() != 3 || loop[0] != 8'h90 || loop[1] != 8'h3c || loop[2] != 8'h40
            || ferrs != 0) begin
            $display("FAIL tx 9600: %p ferrs %0d", loop, ferrs); errors++;
        end

        if (errors == 0) $display("midi_card OK");
        else $display("midi_card FAILED: %0d errors", errors);
        $finish;
    end
endmodule
