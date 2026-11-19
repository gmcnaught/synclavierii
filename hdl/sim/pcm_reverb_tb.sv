// Self-checking test of hdl/dev/pcm_reverb.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/pcm.py Reverb:
//   V kind mix l r   an input sample (pcm_out's v), the OSD Reverb codes
//   X l r            the output for the next V is (l, r) (before its V line)
// Inputs come every GAP clocks (pcm_out gives one at most every 512); an
// input that arrives while the reverb is still busy is an error.
module pcm_reverb_tb;
    localparam int GAP = 300;
    logic        clk = 0, rst = 1;
    logic [1:0]  kind = 0, mix = 0;
    logic        in_valid = 0;
    logic signed [21:0] in_l = 0, in_r = 0;
    logic        out_valid;
    logic signed [21:0] out_l, out_r;
    int          errors = 0, lines = 0, outs = 0, busy_max = 0, busy = 0;

    pcm_reverb dut (.clk, .rst, .kind, .mix, .in_valid, .in_l, .in_r, .out_valid, .out_l, .out_r);

    always #5 clk = !clk;

    longint want_l [$], want_r [$];
    always @(posedge clk) begin
        if (in_valid && dut.st != dut.IDLE) begin
            errors++;
            $display("input %0d while busy", lines);
        end
        busy = dut.st != dut.IDLE ? busy + 1 : 0;
        if (busy > busy_max) busy_max = busy;
        if (out_valid) begin
            if (want_l.size() == 0) begin
                errors++;
                $display("output %0d not expected", outs);
            end else begin
                if (longint'(out_l) != want_l[0] || longint'(out_r) != want_r[0]) begin
                    errors++;
                    if (errors < 20) $display("output %0d: %0d %0d, expected %0d %0d",
                                              outs, out_l, out_r, want_l[0], want_r[0]);
                end
                void'(want_l.pop_front()); void'(want_r.pop_front());
            end
            outs++;
        end
    end

    initial begin
        string path;
        int fd, code;
        byte k;
        longint a, b, c, e;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c %d %d", k, a, b);
            if (code < 3) break;
            if (k == "V") code = $fscanf(fd, " %d %d", c, e);
            lines++;
            if (k == "X") begin want_l.push_back(a); want_r.push_back(b); end
            else begin
                @(negedge clk); in_valid = 1; kind = 2'(a); mix = 2'(b); in_l = 22'(c); in_r = 22'(e);
                @(negedge clk); in_valid = 0;
                repeat (GAP - 1) @(negedge clk);
            end
        end
        repeat (GAP) @(posedge clk);
        if (want_l.size() > 0) begin
            errors++;
            $display("%0d outputs expected, not put out", want_l.size());
        end
        if (errors == 0 && outs > 0) $display("pcm_reverb OK (%0d lines, %0d outputs, busy at most %0d clocks)",
                                              lines, outs, busy_max);
        else $display("pcm_reverb FAILED: %0d errors", errors);
        $finish;
    end
endmodule
