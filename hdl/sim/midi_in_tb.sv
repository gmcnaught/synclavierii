// Self-checking test of hdl/core/midi_in.sv (verilator --binary): MIDI
// bytes on the serial line -> the keyboard/panel words written, and the
// program-change button timing. 1 MHz clock, 31250 baud (32 clocks a bit).
module midi_in_tb;
    localparam longint HZ = 1_000_000;
    logic        clk = 0, rst = 1, rxd = 1;
    logic        host_we, host_panel;
    logic [2:0]  host_index;
    logic [15:0] host_value;
    logic        byte_valid, frame_err, alt;
    logic [7:0]  byte_data;
    logic        msg_valid;
    logic [2:0]  msg_kind;
    logic [3:0]  msg_chan;
    logic [6:0]  msg_m1, msg_m2;
    longint      cyc = 0;

    // decoded messages: {kind, chan, m1, m2}
    logic [20:0] msgs [$];
    always @(posedge clk) if (msg_valid) msgs.push_back({msg_kind, msg_chan, msg_m1, msg_m2});

    midi_in #(.CLK_HZ(HZ)) dut (.*);

    always #5 clk = !clk;

    // writes seen: {panel, index, value} and when
    logic [19:0] got [$];
    longint      at [$];
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (host_we) begin
            got.push_back({host_panel, host_index, host_value});
            at.push_back(cyc);
        end
    end

    int bit_clocks = 32;                     // 31250 baud at 1 MHz; 104 for 9600
    task automatic send(input logic [7:0] b);
        rxd = 0; repeat (bit_clocks) @(negedge clk);
        for (int i = 0; i < 8; i++) begin rxd = b[i]; repeat (bit_clocks) @(negedge clk); end
        rxd = 1; repeat (bit_clocks + 8) @(negedge clk);
    endtask

    function automatic logic [19:0] w(input logic p, input int i, input logic [15:0] v);
        return {p, 3'(i), v};
    endfunction

    int errors = 0;
    task automatic expect_writes(input logic [19:0] want [$]);
        repeat (20) @(negedge clk);
        if (got.size() != want.size()) begin
            $display("FAIL: %0d writes, expected %0d", got.size(), want.size());
            errors++;
        end
        for (int i = 0; i < want.size() && i < got.size(); i++)
            if (got[i] !== want[i]) begin
                $display("FAIL: write %0d = %05h, expected %05h", i, got[i], want[i]);
                errors++;
            end
        got.delete();
        at.delete();
    endtask

    initial begin
        repeat (5) @(negedge clk);
        rst = 0;
        repeat (5) @(negedge clk);
        // note on 60, running status note on 64, note on 60 velocity 0, note off 64
        send(8'h90); send(8'd60); send(8'd100);
        send(8'd64); send(8'd100);
        send(8'd60); send(8'd0);
        send(8'h80); send(8'd64); send(8'd0);
        expect_writes('{w(0, 2, 16'h0ffe), w(0, 2, 16'h0fee), w(0, 2, 16'h0fef), w(0, 2, 16'h0fff)});
        // a timing clock inside a message; note 24 folds up to 36
        send(8'h91); send(8'hf8); send(8'd36); send(8'd1);
        send(8'd24); send(8'd1);
        send(8'h81); send(8'd36); send(8'd0);
        expect_writes('{w(0, 0, 16'h0ffe), w(0, 0, 16'h0ffe), w(0, 0, 16'h0fff)});
        // top C (96), 108 folds to 96; all notes off releases everything
        send(8'h92); send(8'd96); send(8'd1); send(8'd108); send(8'd1);
        send(8'hb2); send(8'd123); send(8'd0);
        expect_writes('{w(0, 5, 16'h0000), w(0, 5, 16'h0000),
                        w(0, 0, 16'h0fff), w(0, 1, 16'h0fff), w(0, 2, 16'h0fff),
                        w(0, 3, 16'h0fff), w(0, 4, 16'h0fff), w(0, 5, 16'h0001)});
        // channel 16: panel button 104 (timb.0) down and up; SysEx skipped
        send(8'h9f); send(8'd104); send(8'd1);
        send(8'hf0); send(8'h43); send(8'h10); send(8'hf7);
        send(8'h8f); send(8'd104); send(8'd0);
        expect_writes('{w(1, 6, 16'h0100), w(1, 6, 16'h0000)});
        // program change 11: bank.1 for 100 ms; 1.5 s later timb.3 for 100 ms
        send(8'hc0); send(8'd11);
        repeat (1800 * 1000) @(negedge clk);
        if (got.size() == 4 && at[1] - at[0] >= 99_000 && at[1] - at[0] <= 101_000 &&
            at[2] - at[0] >= 1_599_000 && at[2] - at[0] <= 1_601_000 &&
            at[3] - at[2] >= 99_000 && at[3] - at[2] <= 101_000) ;
        else begin
            $display("FAIL: program change timing (%0d writes)", got.size());
            errors++;
        end
        expect_writes('{w(1, 6, 16'h0002), w(1, 6, 16'h0000), w(1, 6, 16'h0800), w(1, 6, 16'h0000)});
        if (alt) begin $display("FAIL: switched off 31250 on a 31250 line"); errors++; end
        // the line falls back to 9600 (MiSTer ttyS1): MIDI clock bytes, then a note
        bit_clocks = 104;
        repeat (12) send(8'hf8);
        if (!alt) begin $display("FAIL: did not switch to 9600"); errors++; end
        got.delete(); at.delete();
        send(8'h90); send(8'd60); send(8'd100); send(8'd60); send(8'd0);
        expect_writes('{w(0, 2, 16'h0ffe), w(0, 2, 16'h0fff)});
        // and back to 31250
        bit_clocks = 32;
        repeat (12) send(8'hf8);
        if (alt) begin $display("FAIL: did not return to 31250"); errors++; end
        send(8'h90); send(8'd64); send(8'd100);
        expect_writes('{w(0, 2, 16'h0fef)});
        // decoded messages: pitch bend, key pressure (running status), channel
        // pressure, control change; none of them writes the keyboard
        msgs.delete();
        send(8'he3); send(8'h12); send(8'h40);
        send(8'ha4); send(8'd60); send(8'd70); send(8'd62); send(8'd71);
        send(8'hd5); send(8'd99);
        send(8'hb0); send(8'd21); send(8'd5);
        expect_writes('{});
        if (msgs.size() != 5 || msgs[0] !== {3'd4, 4'd3, 7'h12, 7'h40} ||
            msgs[1] !== {3'd5, 4'd4, 7'd60, 7'd70} || msgs[2] !== {3'd5, 4'd4, 7'd62, 7'd71} ||
            msgs[3] !== {3'd6, 4'd5, 7'd99, 7'd0} || msgs[4] !== {3'd3, 4'd0, 7'd21, 7'd5}) begin
            $display("FAIL: decoded messages (%0d)", msgs.size());
            errors++;
        end
        if (errors != 0) $fatal(1);
        $display("midi_in OK");
        $finish;
    end
endmodule
