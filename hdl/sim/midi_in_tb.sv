// Self-checking test of hdl/core/midi_in.sv (verilator --binary): MIDI
// bytes on the serial line -> the keyboard/panel words written, and the
// program-change button timing. 1 MHz clock, 31250 baud (32 clocks a bit).
module midi_in_tb;
    localparam longint HZ = 1_000_000;
    logic        clk = 0, rst = 1, rxd = 1;
    logic        host_we, host_panel;
    logic [2:0]  host_index;
    logic [15:0] host_value;
    logic        byte_valid;
    logic [7:0]  byte_data;
    longint      cyc = 0;

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

    task automatic send(input logic [7:0] b);
        rxd = 0; repeat (32) @(negedge clk);
        for (int i = 0; i < 8; i++) begin rxd = b[i]; repeat (32) @(negedge clk); end
        rxd = 1; repeat (40) @(negedge clk);
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
        if (errors != 0) $fatal(1);
        $display("midi_in OK");
        $finish;
    end
endmodule
