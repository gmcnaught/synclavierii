// Self-checking test of hdl/dev/poly_box.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/pcm.py PolyBox:
//   K n i d    a voice tick of n ns; i = 1: a sample instant d ns into it
//              (held while `stall`, as voice time is in lockstep)
//   F l r      dev_fm's sample (the next instant's)
//   P l r      dev_poly's next P(m)
//   X l r      the next x' out is (l, r)
//   W n        n clocks pass
// +fm_level=N, +poly_level=N: the OSD level codes (#76; default 0).
// The checker queues both sides (outputs may come before their X lines).
module poly_box_tb;
    logic        clk = 0, rst = 1;
    logic        tick = 0, inst = 0, fm_valid = 0, p_valid = 0;
    logic [9:0]  tick_ns = 0, inst_d = 0;
    logic signed [39:0] fm_l = 0, fm_r = 0;
    logic signed [31:0] p_l = 0, p_r = 0;
    logic        out_valid, stall;
    logic signed [26:0] out_l, out_r;
    logic [15:0] late;
    logic [1:0]  fm_level = 0, poly_level = 0;
    int          errors = 0, lines = 0, outs = 0, stalls = 0;

    poly_box dut (
        .clk, .rst, .en(1'b1), .fm_level, .poly_level, .hold_ok(1'b1), .tick, .tick_ns, .inst, .inst_d, .fm_valid, .fm_l, .fm_r,
        .p_valid, .p_l, .p_r, .out_valid, .out_l, .out_r, .stall, .late
    );

    always #5 clk = !clk;

    longint want_l [$], want_r [$], got_l [$], got_r [$];
    always @(posedge clk) begin
        if (stall) stalls++;
        if (out_valid) begin got_l.push_back(longint'(out_l)); got_r.push_back(longint'(out_r)); end
        while (got_l.size() > 0 && want_l.size() > 0) begin
            if (got_l[0] != want_l[0] || got_r[0] != want_r[0]) begin
                errors++;
                if (errors < 20) $display("line %0d: x'(%0d) %0d %0d, expected %0d %0d (t_prev %0d nb %0d P %0d, %0d waiting)",
                                          lines, outs, got_l[0], got_r[0], want_l[0], want_r[0],
                                          dut.t_prev, dut.nb, dut.pq_n, dut.fq_n);
            end
            outs++;
            void'(got_l.pop_front()); void'(got_r.pop_front());
            void'(want_l.pop_front()); void'(want_r.pop_front());
        end
    end

    always @(posedge clk)
        if (dut.go && dut.bnd && !dut.p_have && errors == 0)
            $display("line %0d: late (t %0d, nb %0d, %0d waiting, now %0d)", lines, dut.t_head, dut.nb, dut.fq_n, dut.now);

    initial begin
        string path;
        int fd, code;
        byte k;
        longint a, b, c;
        int lv;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        if ($value$plusargs("fm_level=%d", lv)) fm_level = 2'(lv);
        if ($value$plusargs("poly_level=%d", lv)) poly_level = 2'(lv);
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c %d", k, a);
            if (code < 2) break;
            if (k != "W") code = $fscanf(fd, " %d", b);
            if (k == "K") code = $fscanf(fd, " %d", c);
            lines++;
            if (k == "K") begin                  // held while stall, as the CPU is (lockstep)
                @(negedge clk);
                while (stall) @(negedge clk);
                tick = 1; tick_ns = 10'(a); inst = b != 0; inst_d = 10'(c);
                @(negedge clk); tick = 0; inst = 0;
            end else if (k == "F") begin
                @(negedge clk); fm_valid = 1; fm_l = 40'(a); fm_r = 40'(b);
                @(negedge clk); fm_valid = 0;
            end else if (k == "P") begin
                @(negedge clk); p_valid = 1; p_l = 32'(a); p_r = 32'(b);
                @(negedge clk); p_valid = 0;
            end else if (k == "W") repeat (int'(a)) @(posedge clk);
            else if (k == "X") begin want_l.push_back(a); want_r.push_back(b); end
        end
        for (int i = 0; i < 1000 && want_l.size() > 0; i++) @(posedge clk);
        repeat (2) @(posedge clk);
        if (want_l.size() > 0 || got_l.size() > 0) begin
            errors++;
            $display("%0d outputs expected, not put out; %0d put out, not expected", want_l.size(), got_l.size());
        end
        if (late != 16'd0) begin
            errors++;
            $display("late = %0d (the stimulus never makes P late)", late);
        end
        if (errors == 0 && outs > 0)
            $display("poly_box OK (%0d lines, %0d outputs, stall on %0d clocks)", lines, outs, stalls);
        else $display("poly_box FAILED: %0d errors", errors);
        $finish;
    end
endmodule
