// Self-checking test of hdl/dev/dev_poly.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/devices/poly.py:
//   T n        simulated time passes: n ns
//   W r v      write register r (0 D154 .. 3 D157) with v
//   R r v      read register r, expect v
//   Y l r      the next P(m) the device puts out is (l, r) (M26; given
//              before the T that makes it)
//   P n        M19: the output pair heard (0 the stereo mix)
//   D v s t    M19: distributor routing tag t ({connected, output}) for
//              poly voice v (32 x bin + channel), side s (0 left, 1 right)
//   L v s e    M19: expect the level detector's answer e for voice v side s
// Poly memory is a word array behind a port that answers a few clocks late,
// and behind the line fetch stream: commands taken on some clocks, the
// 64-bit beat back in order 12 clocks later (as the board bench's DDR3). +bins=N +units=N
// set the bins and the memory per bin (128 KB units; default 1, 256);
// +last=N the voices in the last bin (default 32), +mono=1 mono voice cards,
// +ftest=N the DDR3 load test (the P values must not change).
module dev_poly_tb;
    logic        clk = 0, rst = 1;
    logic        tick = 0;
    logic [9:0]  tick_ns = 0;
    logic        sel = 0, rd = 0, wr = 0;
    logic [1:0]  reg_sel = 0;
    logic [15:0] wdata = 0, rdata;
    logic        ack;
    logic [23:0] m_addr;
    logic        m_rd, m_wr, m_wide, m_ack = 0;
    logic [15:0] m_wdata, m_rdata = 0;
    logic        p_valid;
    logic signed [31:0] p_l, p_r;
    logic [23:0] s_addr;
    logic        s_rd, s_ack = 0, s_rvalid = 0;
    logic [63:0] s_rdata = 0;
    logic [2:0]  bin_count = 3'd1;
    logic [10:0] units = 11'd256;
    logic [5:0]  last = 6'd32;
    logic        mono = 1'b0;
    logic [1:0]  ftest = 2'd0;
    logic [3:0]  out_pair = 0;
    logic        rt_we = 0, rt_side = 0, q_side = 0, q_live;
    logic [6:0]  rt_voice = 0, q_voice = 0;
    logic [4:0]  rt_tag = 0;
    int          errors = 0, lines = 0, reads = 0, mixes = 0;

    dev_poly dut (
        .clk, .rst, .enable(1'b1), .bin_count, .size_units(units),
        .last_voices(last), .mono, .ftest, .tick, .tick_ns,
        .sel, .rd, .wr, .reg_sel, .wdata, .rdata, .ack,
        .m_addr, .m_rd, .m_wr, .m_wide, .m_wdata, .m_rdata, .m_ack, .clearing(),
        .s_addr, .s_rd, .s_ack, .s_rvalid, .s_rdata,
        .p_valid, .p_l, .p_r,
        .out_pair, .rt_we, .rt_voice, .rt_side, .rt_tag, .q_voice, .q_side, .q_live
    );

    always #5 clk = !clk;

    logic [15:0] mem [1 << 24];
    initial for (int i = 0; i < (1 << 24); i++) mem[i] = 16'h5A5A;   // the clear must zero it
    int dly = 0;
    always @(posedge clk) begin
        m_ack <= 1'b0;
        if ((m_rd || m_wr) && !m_ack) begin
            if (dly == 3) begin
                dly <= 0;
                if (m_wr && m_wide) for (int j = 0; j < 512; j++) mem[{m_addr[23:9], 9'(j)}] <= m_wdata;
                else if (m_wr) mem[m_addr] <= m_wdata;
                m_rdata <= mem[m_addr];
                m_ack <= 1'b1;
            end else dly <= dly + 1;
        end
    end

    // the line fetch stream: a command is taken on 2 clocks of 3; its beat
    // comes back 12 clocks later, in order, one per clock at most
    longint      cyc = 0;
    longint      due [$];
    logic [63:0] dat [$];
    int          s_max = 0, s_total = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        s_ack <= 1'b0;
        s_rvalid <= 1'b0;
        if (due.size() > 0 && due[0] <= cyc) begin
            s_rvalid <= 1'b1; s_rdata <= dat[0];
            void'(due.pop_front()); void'(dat.pop_front());
        end
        if (s_rd && !s_ack && cyc % 3 != 1) begin
            s_ack <= 1'b1;
            s_total++;
            due.push_back(cyc + 12);
            dat.push_back({mem[{s_addr[23:2], 2'd3}], mem[{s_addr[23:2], 2'd2}],
                           mem[{s_addr[23:2], 2'd1}], mem[{s_addr[23:2], 2'd0}]});
            if (due.size() + 1 > s_max) s_max = due.size() + 1;
        end
    end

    // P(m) as it comes out, against the expected values given by Y lines
    // (either may come first)
    longint      want_l [$], want_r [$], got_l [$], got_r [$];
    always @(posedge clk) begin
        if (p_valid) begin got_l.push_back(longint'(p_l)); got_r.push_back(longint'(p_r)); end
        while (got_l.size() > 0 && want_l.size() > 0) begin
            if (got_l[0] != want_l[0] || got_r[0] != want_r[0]) begin
                errors++;
                if (errors < 20) $display("line %0d: P(%0d) %0d %0d, expected %0d %0d", lines, mixes,
                                          got_l[0], got_r[0], want_l[0], want_r[0]);
                if (errors == 1)
                    for (int i = 0; i < 32 * bin_count; i++)
                        if (dut.on0[i] || dut.dac_on[i] || (i % 2 == 1 && dut.master[i - 1]))
                            $display("  v%0d on %0d%0d dac %0d pos %0d acc %0d", i, dut.on1[i], dut.on0[i],
                                     dut.dac_on[i], $signed(dut.vr_mem[i][38:9]), dut.vr_mem[i][8:0]);
            end
            mixes++;
            void'(got_l.pop_front()); void'(got_r.pop_front());
            void'(want_l.pop_front()); void'(want_r.pop_front());
        end
    end

    task automatic access(input logic [1:0] r, input logic is_rd, input logic [15:0] v,
                          output logic [15:0] got);
        @(negedge clk);
        sel = 1; reg_sel = r; rd = is_rd; wr = !is_rd; wdata = v;
        do @(posedge clk); while (!ack);
        got = rdata;
        @(negedge clk);
        sel = 0; rd = 0; wr = 0;
    endtask

    // routing and output pair changes apply from the current time on: wait
    // for the passes up to now (the model has run them)
    task automatic settle();
        do @(posedge clk); while (dut.es != 4'd1 || dut.rate_due || dut.env_due || !dut.fetch_idle);
    endtask

    task automatic pass_time(input longint n);
        while (n > 0) begin
            @(negedge clk);
            tick = 1; tick_ns = n > 1000 ? 10'd1000 : 10'(n);
            n -= tick_ns;
            @(negedge clk);
            tick = 0;
        end
    endtask

    initial begin
        string path;
        int fd, code, a, b, c;
        byte k;
        logic [15:0] got;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        if ($value$plusargs("bins=%d", a)) bin_count = 3'(a);
        if ($value$plusargs("units=%d", a)) units = 11'(a);
        if ($value$plusargs("last=%d", a)) last = 6'(a);
        if ($value$plusargs("mono=%d", a)) mono = a != 0;
        if ($value$plusargs("ftest=%d", a)) ftest = 2'(a);   // DDR3 load test: P must not change
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        repeat (1100) @(posedge clk);                // RAM clear (then poly memory: accesses wait)
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c %d", k, a);
            if (code < 2) break;
            if (k != "P") code = $fscanf(fd, " %d", b);
            if (k == "D" || k == "L") code = $fscanf(fd, " %d", c);
            lines++;
            if (k == "T") pass_time(longint'(a));
            else if (k == "P") begin settle(); @(negedge clk); out_pair = 4'(a); end
            else if (k == "D") begin
                settle(); @(negedge clk); rt_we = 1; rt_voice = 7'(a); rt_side = b[0]; rt_tag = 5'(c);
                @(negedge clk); rt_we = 0;
            end else if (k == "L") begin
                @(negedge clk); q_voice = 7'(a); q_side = b[0];
                @(posedge clk);
                reads++;
                if (q_live !== c[0]) begin
                    errors++;
                    if (errors < 20) $display("line %0d: live v%0d side %0d = %0d, expected %0d", lines, a, b, q_live, c);
                end
            end
            else if (k == "W") access(2'(a), 1'b0, 16'(b), got);
            else if (k == "R") begin
                access(2'(a), 1'b1, 16'd0, got);
                reads++;
                if (got !== 16'(b)) begin
                    errors++;
                    if (errors < 20) $display("line %0d: read D%0o = %0d, expected %0d", lines, 9'o154 + a, got, b);
                end
            end else if (k == "Y") begin
                want_l.push_back(longint'(a)); want_r.push_back(longint'(b));
            end
        end
        for (int i = 0; i < 200000 && want_l.size() > 0; i++) @(posedge clk);
        repeat (2) @(posedge clk);
        if (want_l.size() > 0 || got_l.size() > 0) begin
            errors++;
            $display("%0d P values expected, not put out; %0d put out, not expected",
                     want_l.size(), got_l.size());
        end
        if (errors == 0 && lines > 0)
            $display("dev_poly OK (%0d lines, %0d reads, %0d P values, %0d line fetches, %0d in flight at most)",
                     lines, reads, mixes, s_total, s_max);
        else $display("dev_poly FAILED: %0d errors", errors);
        $finish;
    end
endmodule
