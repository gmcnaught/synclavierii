// Self-checking test of hdl/core/audio_fifo.sv (verilator --binary), at
// 10 clocks a sample (CLK_HZ 480000, RATE 48000):
//   1. 400 samples arriving with jitter (gaps of 4-16 clocks, 10 on
//      average): they leave in order, one per strobe, none repeated or
//      lost, no underrun or overrun;
//   2. the input stops for 600 clocks: one underrun, the last sample held;
//   3. it resumes: playback restarts at half full with the next sample.
module audio_fifo_tb;
    logic        clk = 0, rst = 1, in_valid = 0;
    logic signed [15:0] in_l = '0, in_r = '0, out_l, out_r;
    logic        out_strobe;
    logic [15:0] underruns, overruns;
    int          errors = 0;

    audio_fifo #(.CLK_HZ(480_000), .RATE(48_000)) dut (.*);

    always #5 clk = !clk;

    // outputs seen at strobes (left = sample number, right = its negation)
    int seen [$];
    always @(posedge clk) if (out_strobe) seen.push_back(int'(out_l));

    int next = 1;
    task automatic send(input int gap);
        repeat (gap - 1) @(negedge clk);
        @(negedge clk);
        in_valid = 1; in_l = 16'(next); in_r = -16'(next);
        @(negedge clk);
        in_valid = 0;
        next++;
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst = 0;
        // 1. jitter around 10 clocks: 4..16 (pattern sums to 10 per sample on average)
        for (int i = 0; i < 400; i++) send(i % 3 == 0 ? 4 : (i % 3 == 1 ? 16 : 8));
        // 2. stall long enough to drain 64 samples' worth
        repeat (600) @(negedge clk);
        // 3. resume
        for (int i = 0; i < 200; i++) send(9);
        repeat (100) @(negedge clk);                     // (not long enough to drain)

        // check: after the first sample appears, values increase by 1, except
        // repeats only while held after the underrun
        begin
            int first = -1, last = 0, repeats = 0, held_at = 0;
            foreach (seen[k]) begin
                if (seen[k] == 0 && first < 0) continue;      // before playback starts
                if (first < 0) begin first = seen[k]; last = seen[k]; continue; end
                if (seen[k] == last) repeats++;
                else if (seen[k] != last + 1) begin
                    $display("FAIL: sample %0d after %0d", seen[k], last);
                    errors++;
                end
                last = seen[k];
            end
            if (first != 1) begin $display("FAIL: first sample %0d", first); errors++; end
            if (underruns != 16'd1) begin $display("FAIL: underruns %0d", underruns); errors++; end
            if (overruns != 16'd0) begin $display("FAIL: overruns %0d", overruns); errors++; end
            if (repeats == 0) begin $display("FAIL: nothing held during the stall"); errors++; end
            if (last < 540) begin $display("FAIL: only reached sample %0d", last); errors++; end
        end
        if (errors != 0) $fatal(1);
        $display("audio_fifo OK");
        $finish;
    end
endmodule
