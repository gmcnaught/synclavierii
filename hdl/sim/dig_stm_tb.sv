// Self-checking test of hdl/core/dig_stm.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/devices/digstm.py
// DigitalStm:
//   F n w0 .. w(n-1)   the source file (S5) as words; present
//   A                  no source file (absent)
//   M                  S5 mounted again (the header is read at the next call)
//   T ns k             k CPU ticks of ns each, one a clock
//   C n r0 r1 r2 wr v  native routine 64 + n with R0-R2; the answer must have
//                      nat_wr = wr and, if wr, nat_result = v
//   W v                the next D157 write must be v
// The SD word port answers after 1-6 clocks, dev_poly's after 1-9 (random),
// with the clock after each ack ignored, as sd_floppy and dev_poly do.
module dig_stm_tb;
    logic        clk = 0, rst = 1;
    logic        tick = 0;
    logic [9:0]  tick_ns = 0;
    logic        src_mounted = 0, src_present = 0;
    logic        nat_req = 0, nat_ack, nat_wr;
    logic [3:0]  nat_num = 0;
    logic [15:0] r0 = 0, r1 = 0, r2 = 0, nat_result;
    logic [23:0] s_addr;
    logic        s_rd, s_ack = 0, p_wr, p_ack = 0;
    logic [15:0] s_rdata = 0, p_wdata;
    logic [15:0] file [int];
    int          errors = 0, calls = 0, results = 0, pwrites = 0, sreads = 0, lines = 0;
    logic [15:0] want_w [$];
    int          s_wait = 0, p_wait = 0;
    logic        s_skip = 0, p_skip = 0;

    dig_stm dut (.clk, .rst, .tick, .tick_ns, .src_mounted, .src_present,
                 .nat_req, .nat_num, .r0, .r1, .r2, .nat_ack, .nat_wr, .nat_result,
                 .s_addr, .s_rd, .s_rdata, .s_ack, .p_wr, .p_wdata, .p_ack);

    always #5 clk = !clk;

    // SD word port and dev_poly's register port
    always @(posedge clk) begin
        s_ack <= 1'b0;
        p_ack <= 1'b0;
        s_skip <= s_ack;
        p_skip <= p_ack;
        if (s_rd && !s_ack && !s_skip) begin
            if (s_wait == 0) s_wait <= 1 + $urandom_range(0, 5);
            else if (s_wait == 1) begin
                s_wait <= 0;
                s_ack <= 1'b1;
                sreads++;
                s_rdata <= file.exists(int'(s_addr)) ? file[int'(s_addr)] : 16'd0;
            end else s_wait <= s_wait - 1;
        end
        if (p_wr && !p_ack && !p_skip) begin
            if (p_wait == 0) p_wait <= 1 + $urandom_range(0, 8);
            else if (p_wait == 1) begin
                p_wait <= 0;
                p_ack <= 1'b1;
                pwrites++;
                if (want_w.size() == 0) begin
                    errors++;
                    if (errors < 20) $display("unexpected D157 write %0d", p_wdata);
                end else begin
                    if (p_wdata !== want_w[0]) begin
                        errors++;
                        if (errors < 20) $display("D157 write %0d: %0d, expected %0d", pwrites, p_wdata, want_w[0]);
                    end
                    void'(want_w.pop_front());
                end
            end else p_wait <= p_wait - 1;
        end
    end

    initial begin
        string path;
        int fd, code, n, a, b, c, d, wr, v, cyc;
        byte k;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        @(negedge clk) rst = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c", k);
            if (code < 1) break;
            lines++;
            if (k == "F") begin
                code = $fscanf(fd, " %d", n);
                file.delete();
                for (int i = 0; i < n; i++) begin
                    code = $fscanf(fd, " %d", v);
                    file[i] = 16'(v);
                end
                src_present = 1;
            end else if (k == "A") begin
                file.delete();
                src_present = 0;
            end else if (k == "M") begin
                @(negedge clk) src_mounted = 1;
                @(negedge clk) src_mounted = 0;
            end else if (k == "T") begin
                code = $fscanf(fd, " %d %d", a, b);
                for (int i = 0; i < b; i++) begin
                    @(negedge clk) tick = 1; tick_ns = 10'(a);
                end
                @(negedge clk) tick = 0;
            end else if (k == "W") begin
                code = $fscanf(fd, " %d", v);
                want_w.push_back(16'(v));
            end else if (k == "C") begin
                code = $fscanf(fd, " %d %d %d %d %d %d", n, a, b, c, wr, v);
                calls++;
                @(negedge clk);
                nat_req = 1; nat_num = 4'(n); r0 = 16'(a); r1 = 16'(b); r2 = 16'(c);
                cyc = 0;
                do begin
                    @(posedge clk); #1;
                    cyc++;
                end while (!nat_ack && cyc < 100000);
                if (!nat_ack) begin
                    errors++; $display("line %0d: routine %0d not answered", lines, 64 + n);
                    $finish;
                end
                if (nat_wr !== 1'(wr) || (wr != 0 && nat_result !== 16'(v))) begin
                    errors++;
                    if (errors < 20)
                        $display("line %0d: routine %0d: wr %0d result %0d, expected wr %0d result %0d",
                                 lines, 64 + n, nat_wr, nat_result, wr, v);
                end
                if (wr != 0) results++;
                @(negedge clk) nat_req = 0;
                if (want_w.size() != 0) begin
                    errors++; $display("line %0d: %0d D157 writes missing", lines, want_w.size());
                    want_w.delete();
                end
            end
        end
        if (errors == 0)
            $display("dig_stm OK: %0d calls, %0d results, %0d D157 writes, %0d source reads",
                     calls, results, pwrites, sreads);
        else $display("dig_stm FAILED: %0d errors", errors);
        $finish;
    end
endmodule
