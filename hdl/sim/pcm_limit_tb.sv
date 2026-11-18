// Self-checking test of hdl/dev/pcm_limit.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/pcm.py Limiter:
//   V on l r   an input sample (pcm_out's v), the limiter on or off
//   X l r      the output for the next V is (l, r) (before its V line)
// Inputs come every GAP clocks (pcm_out gives one at most every 512).
module pcm_limit_tb;
    localparam int GAP = 48;
    logic        clk = 0, rst = 1;
    logic        on = 1, in_valid = 0;
    logic signed [21:0] in_l = 0, in_r = 0;
    logic        out_valid;
    logic signed [15:0] out_l, out_r;
    int          errors = 0, lines = 0, outs = 0;

    pcm_limit dut (.clk, .rst, .on, .in_valid, .in_l, .in_r, .out_valid, .out_l, .out_r);

    always #5 clk = !clk;

    longint want_l [$], want_r [$];
    always @(posedge clk) begin
        if (out_valid) begin
            if (want_l.size() == 0) begin
                errors++;
                $display("output %0d not expected", outs);
            end else begin
                if (longint'(out_l) != want_l[0] || longint'(out_r) != want_r[0]) begin
                    errors++;
                    if (errors < 20) $display("output %0d: %0d %0d, expected %0d %0d (g %0d hold %0d)",
                                              outs, out_l, out_r, want_l[0], want_r[0], dut.g, dut.hold);
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
        longint a, b, c;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c %d %d", k, a, b);
            if (code < 3) break;
            if (k == "V") code = $fscanf(fd, " %d", c);
            lines++;
            if (k == "X") begin want_l.push_back(a); want_r.push_back(b); end
            else begin
                @(negedge clk); in_valid = 1; on = a != 0; in_l = 22'(b); in_r = 22'(c);
                @(negedge clk); in_valid = 0;
                repeat (GAP - 1) @(negedge clk);
            end
        end
        repeat (GAP) @(posedge clk);
        if (want_l.size() > 0) begin
            errors++;
            $display("%0d outputs expected, not put out", want_l.size());
        end
        if (errors == 0 && outs > 0) $display("pcm_limit OK (%0d lines, %0d outputs)", lines, outs);
        else $display("pcm_limit FAILED: %0d errors", errors);
        $finish;
    end
endmodule
