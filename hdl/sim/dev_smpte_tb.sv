// Self-checking test of hdl/dev/dev_smpte.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/devices/smpte.py
// SmpteReader:
//   W r v        write register r (0 D70 .. 3 D73) with v
//   R r v        read register r, expect v
//   B b          a MIDI in byte
//   T ns n       n clocks of simulated time, ns each
//   X ns b       a tick of ns and a MIDI in byte in the same clock
module dev_smpte_tb;
    logic        clk = 0, rst = 1;
    logic        sel = 0, rd = 0, wr = 0;
    logic [1:0]  reg_sel = 0;
    logic [15:0] wdata = 0, rdata;
    logic        tick = 0;
    logic [9:0]  tick_ns = 0;
    logic        rx_valid = 0;
    logic [7:0]  rx_data = 0;
    int          errors = 0, lines = 0, reads = 0;

    dev_smpte dut (.clk, .rst, .present(1'b1), .sel, .rd, .wr, .reg_sel, .wdata, .rdata,
                   .tick, .tick_ns, .rx_valid, .rx_data);

    always #5 clk = !clk;

    task automatic access(input int r, input logic is_rd, input logic [15:0] v,
                          output logic [15:0] got);
        @(negedge clk);
        sel = 1; reg_sel = 2'(r); rd = is_rd; wr = !is_rd; wdata = v;
        @(posedge clk);
        got = rdata;
        @(negedge clk);
        sel = 0; rd = 0; wr = 0;
    endtask

    initial begin
        string path;
        int fd, code, a, b;
        byte k;
        logic [15:0] got;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c %d", k, a);
            if (code < 2) break;
            lines++;
            if (k == "W" || k == "R" || k == "T" || k == "X") code = $fscanf(fd, " %d", b);
            if (k == "W") access(a, 1'b0, 16'(b), got);
            else if (k == "R") begin
                access(a, 1'b1, 16'd0, got);
                reads++;
                if (got !== 16'(b)) begin
                    errors++;
                    if (errors < 20) $display("line %0d: D7%0d = %06o, expected %06o", lines, a, got, b);
                end
            end else if (k == "B" || k == "X") begin
                @(negedge clk);
                rx_valid = 1; rx_data = 8'(k == "X" ? b : a);
                tick = k == "X"; tick_ns = 10'(a);
                @(negedge clk);
                rx_valid = 0; tick = 0;
            end else if (k == "T") begin
                @(negedge clk);
                tick = 1; tick_ns = 10'(a);
                repeat (b) @(negedge clk);
                tick = 0;
            end
        end
        if (errors == 0 && reads > 0)
            $display("dev_smpte OK: %0d lines, %0d reads", lines, reads);
        else
            $display("dev_smpte FAILED: %0d errors", errors);
        $finish;
    end
endmodule
