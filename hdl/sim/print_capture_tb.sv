// Self-checking test of hdl/dev/dev_printer.sv and hdl/core/print_capture.sv
// (verilator --binary) against a stimulus file made by tests/hdl/test_board.py
// from sim/devices/printer.py Printer and tools/print_render.py:
//   W r v     write register r (0 D40, 1 D41, 2 D54) with v
//   R r v     read register r, expect v
//   T ns      advance simulated time by ns (ticks of at most 1000 ns)
//   I v       expect the interrupt line to be v
//   Z n       a new SD image of n blocks, all zero (not yet mounted)
//   M         mount the image in the capture's slot
//   U         unmount (a zero-size mount)
//   D         wait until the capture is idle (bytes flushed, header written)
//   N v       expect the last OSD note to be v (1 saved, 2 lost, 3 full)
//   F n       expect the image's header to say n bytes
//   O b       the next byte of the image's data (from block 1) must be b
// The SD side plays hps_io's HPS: one 512-byte block per request, after a
// delay, data on sd_buff_* while sd_ack is high.
module print_capture_tb;
    logic        clk = 0, rst = 1;
    logic        sel = 0, rd = 0, wr = 0, tick = 0;
    logic [9:0]  tick_ns = 0;
    logic [1:0]  reg_sel = 0;
    logic [15:0] wdata = 0, rdata;
    logic        ack, irq, tx_valid;
    logic [7:0]  tx_data;
    logic        img_mounted = 0;
    logic [63:0] img_size = 0;
    logic [31:0] sd_lba;
    logic        sd_rd, sd_wr, sd_ack = 0, sd_buff_wr = 0;
    logic [13:0] sd_buff_addr = 0;
    logic [7:0]  sd_buff_dout = 0, sd_buff_din;
    logic [31:0] count;
    logic        busy, note_valid;
    logic [1:0]  note, last_note = 0;
    int          errors = 0, lines = 0;
    byte         img [];
    int          optr = 0;

    dev_printer dut (.clk, .rst, .tick, .tick_ns, .sel, .rd, .wr, .reg_sel, .wdata, .rdata,
                     .ack, .irq, .tx_valid, .tx_data);
    print_capture #(.IDLE_CLKS(300)) cap (
        .clk, .rst, .in_valid(tx_valid), .in_data(tx_data),
        .img_mounted, .img_readonly(1'b0), .img_size, .sd_lba, .sd_rd, .sd_wr, .sd_ack,
        .sd_buff_addr, .sd_buff_dout, .sd_buff_din, .sd_buff_wr,
        .count, .busy, .note, .note_valid);

    always #5 clk = !clk;
    always @(posedge clk) if (note_valid) last_note <= note;

    // the HPS: serve one request at a time
    initial begin
        forever begin
            @(posedge clk);
            if (sd_rd || sd_wr) begin
                logic w;
                int base;
                w = sd_wr;
                base = int'(sd_lba) * 512;
                repeat (20) @(posedge clk);
                sd_ack <= 1;
                repeat (3) @(posedge clk);
                for (int i = 0; i < 512; i++) begin
                    if (w) begin
                        sd_buff_addr <= 14'(i);
                        repeat (3) @(posedge clk);
                        if (base + i < img.size()) img[base + i] = sd_buff_din;
                    end else begin
                        sd_buff_addr <= 14'(i);
                        sd_buff_dout <= base + i < img.size() ? img[base + i] : 8'd0;
                        sd_buff_wr <= 1;
                        @(posedge clk);
                        sd_buff_wr <= 0;
                        @(posedge clk);
                    end
                end
                sd_ack <= 0;
                repeat (5) @(posedge clk);
            end
        end
    end

    task automatic access(input int r, input logic is_rd, input logic [15:0] v,
                          output logic [15:0] got);
        @(negedge clk);
        sel = 1; reg_sel = 2'(r); rd = is_rd; wr = !is_rd; wdata = v;
        @(posedge clk);
        if (!ack) begin errors++; $display("line %0d: no ack", lines); end
        got = rdata;
        @(negedge clk);
        sel = 0; rd = 0; wr = 0;
    endtask

    initial begin
        string path;
        int fd, code, a, b, n;
        byte k;
        logic [15:0] got;
        if (!$value$plusargs("stim=%s", path)) begin
            $display("no +stim=FILE"); $finish;
        end
        fd = $fopen(path, "r");
        repeat (4) @(posedge clk);
        rst = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, " %c", k);
            if (code < 1) break;
            lines++;
            case (k)
            "W", "R": begin
                code = $fscanf(fd, " %d %d", a, b);
                access(a, k == "R", 16'(b), got);
                if (k == "R" && got != 16'(b)) begin
                    errors++;
                    if (errors < 10) $display("line %0d: read %0d = %0d, want %0d", lines, a, got, b);
                end
            end
            "T": begin
                code = $fscanf(fd, " %d", a);
                while (a > 0) begin
                    @(negedge clk);
                    tick = 1; tick_ns = 10'(a > 1000 ? 1000 : a);
                    a -= 1000;
                    @(negedge clk);
                    tick = 0;
                end
            end
            "I": begin
                code = $fscanf(fd, " %d", a);
                if (irq != a[0]) begin
                    errors++;
                    if (errors < 10) $display("line %0d: irq %0d, want %0d", lines, irq, a);
                end
            end
            "Z": begin
                code = $fscanf(fd, " %d", a);
                img = new[a * 512];
                foreach (img[i]) img[i] = 0;
            end
            "M", "U": begin
                @(negedge clk);
                img_mounted = 1; img_size = k == "M" ? 64'(img.size()) : 64'd0;
                @(negedge clk);
                img_mounted = 0;
                repeat (2) @(negedge clk);
                while (cap.state == 3'd1 || cap.state == 3'd2) @(negedge clk);   // header, last block
            end
            "D": begin
                repeat (2) @(negedge clk);
                n = 0;
                while ((busy || sd_ack || sd_rd || sd_wr) && n < 1000000) begin @(negedge clk); n++; end
                repeat (400) @(negedge clk);                    // a note after the idle time
            end
            "N": begin
                code = $fscanf(fd, " %d", a);
                if (last_note != 2'(a)) begin
                    errors++; $display("line %0d: note %0d, want %0d", lines, last_note, a);
                end
            end
            "F": begin
                code = $fscanf(fd, " %d", a);
                n = {img[10], img[11], img[12], img[13]};
                if (img[0] != "S" || img[7] != "T" || img[9] != 1 || n != a) begin
                    errors++;
                    $display("line %0d: header %c..%c v%0d count %0d, want count %0d",
                             lines, img[0], img[7], img[9], n, a);
                end
                optr = 512;
            end
            "O": begin
                code = $fscanf(fd, " %d", a);
                if (img[optr] != 8'(a)) begin
                    errors++;
                    if (errors < 10) $display("line %0d: file byte %0d = %0d, want %0d",
                                              lines, optr - 512, img[optr], a);
                end
                optr++;
            end
            default: begin $display("bad stimulus '%c'", k); $finish; end
            endcase
        end
        if (errors == 0) $display("print_capture OK: %0d lines", lines);
        else $display("print_capture FAILED: %0d errors", errors);
        $finish;
    end
endmodule
