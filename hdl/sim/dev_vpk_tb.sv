// Self-checking test of hdl/dev/dev_vpk.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/devices/synth.py
// VelocityKeyboard:
//   W r v        write register r (0 D130, 1 D131) with v
//   R r v        read register r, expect v
//   H op a d     host op (dev_vpk.sv header)
//   L a v        expect light address a = v
//   C a v        expect display character a = v
module dev_vpk_tb;
    logic        clk = 0, rst = 1;
    logic        sel = 0, rd = 0, wr = 0, reg_sel = 0;
    logic [15:0] wdata = 0, rdata;
    logic        ack, nosyn;
    logic        host_we = 0;
    logic [2:0]  host_op = 0;
    logic [7:0]  host_addr = 0, host_data = 0;
    logic [1:0]  lights [160];
    logic [7:0]  chars [32];
    logic [7:0]  dp [4];
    int          errors = 0, lines = 0, reads = 0;

    dev_vpk dut (
        .clk, .rst, .sel, .rd, .wr, .reg_sel, .wdata, .rdata, .ack, .nosyn, .strict(1'b1),
        .host_we, .host_op, .host_addr, .host_data, .lights, .chars, .dp
    );

    always #5 clk = !clk;

    task automatic access(input logic r, input logic is_rd, input logic [15:0] v,
                          output logic [15:0] got);
        @(negedge clk);
        sel = 1; reg_sel = r; rd = is_rd; wr = !is_rd; wdata = v;
        @(posedge clk);
        got = rdata;
        @(negedge clk);
        sel = 0; rd = 0; wr = 0;
    endtask

    task automatic check(input string what, input int a, input int got, input int exp);
        if (got !== exp) begin
            errors++;
            if (errors < 20) $display("line %0d: %s %0d = %0d, expected %0d", lines, what, a, got, exp);
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
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c %d %d", k, a, b);
            if (code < 2) break;
            lines++;
            if (k == "W") access(1'(a), 1'b0, 16'(b), got);
            else if (k == "R") begin
                access(1'(a), 1'b1, 16'd0, got);
                reads++;
                check(a ? "D131" : "D130", lines, got, b);
            end else if (k == "H") begin
                code = $fscanf(fd, " %d", c);
                @(negedge clk);
                host_we = 1; host_op = 3'(a); host_addr = 8'(b); host_data = 8'(c);
                @(negedge clk);
                host_we = 0;
            end else if (k == "L") check("light", a, lights[a], b);
            else if (k == "C") check("char", a, chars[a], b);
        end
        if (errors == 0 && reads > 0) $display("dev_vpk OK (%0d lines, %0d reads)", lines, reads);
        else $display("dev_vpk FAILED: %0d errors", errors);
        $finish;
    end
endmodule
