// Self-checking test of hdl/dev/dev_poly.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/devices/poly.py:
//   T n        simulated time passes: n ns
//   W r v      write register r (0 D154 .. 3 D157) with v
//   R r v      read register r, expect v
//   X l r      a mix (FM sample 0): expect the poly mix (l, r)
// Poly memory is a word array behind a port that answers a few clocks late,
// and behind the mix read stream: commands taken on some clocks, data back
// in order 12 clocks later (as the board bench's DDR3). +bins=N +units=N
// set the bins and the memory per bin (128 KB units; default 1, 256).
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
    logic        mix_in_valid = 0, mix_out_valid;
    logic [23:0] s_addr;
    logic        s_rd, s_ack = 0, s_rvalid = 0;
    logic [15:0] s_rdata = 0;
    logic [2:0]  bin_count = 3'd1;
    logic [10:0] units = 11'd256;
    logic signed [15:0] mix_out_l, mix_out_r;
    int          errors = 0, lines = 0, reads = 0, mixes = 0;

    dev_poly dut (
        .clk, .rst, .enable(1'b1), .bin_count, .size_units(units), .tick, .tick_ns,
        .sel, .rd, .wr, .reg_sel, .wdata, .rdata, .ack,
        .m_addr, .m_rd, .m_wr, .m_wide, .m_wdata, .m_rdata, .m_ack, .clearing(),
        .s_addr, .s_rd, .s_ack, .s_rvalid, .s_rdata,
        .mix_in_valid, .mix_in_l(16'sd0), .mix_in_r(16'sd0),
        .mix_out_valid, .mix_out_l, .mix_out_r
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

    // the mix read stream: a command is taken on 2 clocks of 3; its data
    // comes back 12 clocks later, in order, one per clock at most
    longint      cyc = 0;
    longint      due [$];
    logic [15:0] dat [$];
    int          s_max = 0;
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
            due.push_back(cyc + 12); dat.push_back(mem[s_addr]);
            if (due.size() + 1 > s_max) s_max = due.size() + 1;
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
        int fd, code, a, b;
        byte k;
        logic [15:0] got;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        if ($value$plusargs("bins=%d", a)) bin_count = 3'(a);
        if ($value$plusargs("units=%d", a)) units = 11'(a);
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        repeat (1100) @(posedge clk);                // RAM clear (then poly memory: accesses wait)
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c %d %d", k, a, b);
            if (code < 2) break;
            lines++;
            if (k == "T") pass_time(longint'(a));
            else if (k == "W") access(2'(a), 1'b0, 16'(b), got);
            else if (k == "R") begin
                access(2'(a), 1'b1, 16'd0, got);
                reads++;
                if (got !== 16'(b)) begin
                    errors++;
                    if (errors < 20) $display("line %0d: read D%0o = %0d, expected %0d", lines, 9'o154 + a, got, b);
                end
            end else if (k == "X") begin
                @(negedge clk); mix_in_valid = 1; @(negedge clk); mix_in_valid = 0;
                while (!mix_out_valid) @(posedge clk);
                mixes++;
                if (mix_out_l !== 16'(a) || mix_out_r !== 16'(b)) begin
                    errors++;
                    if (errors < 20) $display("line %0d: mix %0d %0d, expected %0d %0d", lines, mix_out_l, mix_out_r, a, b);
                    if (errors == 1)
                        for (int i = 0; i < 32 * bin_count; i++)
                            if (dut.on0[i] || (i % 2 == 1 && dut.master[i - 1]))
                                $display("  v%0d on %0d%0d pos %0d acc %0d", i, dut.on1[i], dut.on0[i],
                                         $signed(dut.vr_mem[i][38:9]), dut.vr_mem[i][8:0]);
                end
            end
        end
        if (errors == 0 && lines > 0)
            $display("dev_poly OK (%0d lines, %0d reads, %0d mixes, %0d mix reads in flight at most)",
                     lines, reads, mixes, s_max);
        else $display("dev_poly FAILED: %0d errors", errors);
        $finish;
    end
endmodule
