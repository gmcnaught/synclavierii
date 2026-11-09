// Self-checking test of hdl/dev/dev_scsi.sv (verilator --binary): the same
// sequences as tests/sim/test_scsi.py (the Python model) on a 4-block disk
// whose bytes are 0, 1, ... 255 repeated, behind a word port that answers
// a few clocks late.
module dev_scsi_tb;
    logic        clk = 0, rst = 1;
    logic        sel = 0, rd = 0, wr = 0;
    logic [1:0]  reg_sel = 0;
    logic [15:0] wdata = 0, rdata;
    logic        ack;
    logic [23:0] d_addr;
    logic        d_rd, d_wr, d_ack;
    logic [15:0] d_wdata, d_rdata;
    int          errors = 0;

    dev_scsi #(.TARGET(4'd5)) dut (
        .clk, .rst, .sel, .rd, .wr, .reg_sel, .wdata, .rdata, .ack,
        .present(1'b1), .protect(1'b0), .blocks(17'd4),
        .present1(1'b0), .protect1(1'b0), .blocks1(17'd0), .d_unit(),
        .d_addr, .d_rd, .d_wr, .d_wdata, .d_rdata, .d_ack
    );

    always #5 clk = !clk;

    // disk: 4 blocks x 256 words, word w = {byte 2w, byte 2w+1}
    logic [15:0] disk [1024];
    int writes = 0;
    initial for (int i = 0; i < 1024; i++) disk[i] = {8'((2 * i) & 255), 8'((2 * i + 1) & 255)};
    int dly = 0;
    always @(posedge clk) begin
        d_ack <= 1'b0;
        if ((d_rd || d_wr) && !d_ack) begin
            dly <= dly + 1;
            if (dly == 3) begin
                dly <= 0;
                d_ack <= 1'b1;
                if (d_wr) begin disk[d_addr[9:0]] <= d_wdata; writes++; end
                d_rdata <= disk[d_addr[9:0]];
            end
        end
    end

    task automatic acc(input logic w, input logic [1:0] r, input logic [15:0] v, output logic [15:0] got);
        @(negedge clk);
        sel = 1; rd = !w; wr = w; reg_sel = r; wdata = v;
        do @(posedge clk); while (!ack);
        got = rdata;
        @(negedge clk);
        sel = 0; rd = 0; wr = 0;
    endtask
    task automatic W(input logic [6:0] dev, input logic [15:0] v);
        logic [15:0] g; acc(1, 2'(dev - 7'o24), v, g);
    endtask
    task automatic R(input logic [6:0] dev, output logic [15:0] v);
        acc(0, 2'(dev - 7'o24), 0, v);
    endtask
    task automatic check_eq(input string what, input logic [15:0] got, input logic [15:0] want);
        if (got !== want) begin $display("FAIL %s: %o, want %o", what, got, want); errors++; end
    endtask

    localparam logic [15:0] ATN = 1, BSY = 2, ACK = 4, MSG = 16, SEL = 32, CD = 64, REQ = 128, IO = 256;

    task automatic connect();
        logic [15:0] v;
        W(7'o24, 16'o10400); R(7'o24, v); check_eq("select bits", v & 16'o7400, 16'o400);
        W(7'o24, 0); R(7'o25, v); check_eq("bus free", v & (BSY | SEL), 0);
        W(7'o25, BSY); W(7'o24, 16'o100); R(7'o24, v); check_eq("arbitration", v & 16'o200, 0);
        W(7'o25, BSY | SEL); W(7'o24, 16'o100 | (1 << 5));
        W(7'o25, BSY | SEL | ATN); W(7'o25, SEL | ATN);
        R(7'o25, v); check_eq("selected", v & BSY, BSY);
        W(7'o24, 0); W(7'o25, ATN);
        R(7'o25, v); check_eq("message out", v & (REQ | MSG | CD), REQ | MSG | CD);
        W(7'o25, 0); W(7'o26, 16'o200);
        R(7'o25, v); check_eq("command phase", v & (REQ | CD | IO | MSG), REQ | CD);
    endtask

    initial begin
        logic [15:0] v, hi, lo;
        repeat (3) @(negedge clk);
        rst = 0;
        // EXTENDED READ of blocks 1-2 with the manual last byte (MONITOR 5.3)
        connect();
        W(7'o26, 16'h28); W(7'o26, 0); W(7'o27, 0); W(7'o27, 1); W(7'o26, 0);
        W(7'o27, 2); W(7'o26, 0);
        R(7'o25, v); check_eq("data in", v & (REQ | IO | CD), REQ | IO);
        R(7'o27, v); check_eq("first word", v, 16'h0001);
        for (int i = 1; i < 511; i++) begin
            R(7'o27, v);
            check_eq("data word", v, {8'((2 * i) & 255), 8'((2 * i + 1) & 255)});
        end
        R(7'o26, hi); check_eq("byte 1022", hi, 16'hFE);
        R(7'o24, lo); check_eq("peeked last byte", lo & 16'o377, 16'hFF);
        W(7'o25, ACK); R(7'o25, v); check_eq("REQ dropped", v & REQ, 0);
        W(7'o25, 0);
        R(7'o25, v); check_eq("status phase", v & (REQ | CD | IO), REQ | CD | IO);
        R(7'o27, v); check_eq("status + message", v, 0);
        R(7'o25, v); check_eq("bus free after", v & (BSY | REQ), 0);
        // WRITE(6) block 1, then a bad command and REQUEST SENSE
        connect();
        W(7'o26, 16'h0A); W(7'o26, 0); W(7'o26, 0); W(7'o26, 1); W(7'o26, 1); W(7'o26, 0);
        R(7'o25, v); check_eq("data out", v & (REQ | IO | CD), REQ);
        for (int i = 0; i < 256; i++) W(7'o27, 16'h1234 + 16'(i));
        R(7'o27, v); check_eq("write status", v >> 8, 0);
        if (disk[256] !== 16'h1234 || disk[511] !== 16'h1333 || writes != 256) begin
            $display("FAIL disk after write: %h %h, %0d writes", disk[256], disk[511], writes); errors++;
        end
        connect();
        for (int i = 0; i < 6; i++) W(7'o26, i == 0 ? 16'h02 : 0);
        R(7'o27, v); check_eq("check condition", v >> 8, 16'h02);
        connect();
        W(7'o26, 16'h03); W(7'o26, 0); W(7'o26, 0); W(7'o26, 0); W(7'o26, 18); W(7'o26, 0);
        R(7'o26, v); check_eq("sense 0", v, 16'h70);
        R(7'o26, v);
        R(7'o26, v); check_eq("sense key", v, 16'h05);
        for (int i = 3; i < 18; i++) R(7'o26, v);
        R(7'o27, v); check_eq("sense status", v, 0);
        // READ CAPACITY: last block 3, 512 bytes
        connect();
        for (int i = 0; i < 10; i++) W(7'o26, i == 0 ? 16'h25 : 0);
        R(7'o27, v); check_eq("capacity hi", v, 0);
        R(7'o27, v); check_eq("capacity lo", v, 3);
        R(7'o27, v); check_eq("block size hi", v, 0);
        R(7'o27, v); check_eq("block size lo", v, 16'h0200);
        R(7'o27, v); check_eq("capacity status", v, 0);
        if (errors != 0) $fatal(1);
        $display("dev_scsi OK");
        $finish;
    end
endmodule
