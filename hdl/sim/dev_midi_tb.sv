// Self-checking test of hdl/dev/dev_midi.sv (verilator --binary) against a
// stimulus file made by tests/hdl/test_board.py from sim/devices/midi.py
// MidiSubsystem:
//   W r v        write register r (0 D70 .. 3 D73) with v
//   R r v        read register r, expect v
//   B b          a byte from the MIDI in jack
//   O b          the next byte on MIDI out must be b (checked at the end)
module dev_midi_tb;
    logic        clk = 0, rst = 1;
    logic        sel = 0, rd = 0, wr = 0;
    logic [1:0]  reg_sel = 0;
    logic [15:0] wdata = 0, rdata;
    logic        ack;
    logic        rx_valid = 0;
    logic [7:0]  rx_data = 0;
    logic        tx_valid, tx_ready;
    logic [7:0]  tx_data;
    int          errors = 0, lines = 0, reads = 0;
    byte         sent [$];
    int          ready_phase = 0;

    dev_midi dut (.clk, .rst, .sel, .rd, .wr, .reg_sel, .wdata, .rdata, .ack,
                  .rx_valid, .rx_data, .tx_valid, .tx_data, .tx_ready);

    always #5 clk = !clk;
    // the sink is ready on 2 clocks of every 3 (back-pressure)
    assign tx_ready = ready_phase != 2;
    always @(posedge clk) begin
        ready_phase <= ready_phase == 2 ? 0 : ready_phase + 1;
        if (!rst && tx_valid && tx_ready) sent.push_back(tx_data);
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
        int fd, code, a, b, n_out;
        byte k;
        byte want [$];
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
            if (k == "W" || k == "R") code = $fscanf(fd, " %d", b);
            if (k == "W") access(a, 1'b0, 16'(b), got);
            else if (k == "R") begin
                access(a, 1'b1, 16'd0, got);
                reads++;
                if (got !== 16'(b)) begin
                    errors++;
                    if (errors < 20) $display("line %0d: D7%0d = %0d, expected %0d", lines, a, got, b);
                end
            end else if (k == "B") begin
                @(negedge clk);
                rx_valid = 1; rx_data = 8'(a);
                @(negedge clk);
                rx_valid = 0;
            end else if (k == "O") want.push_back(8'(a));
        end
        repeat (2000) @(posedge clk);
        n_out = want.size();
        if (sent.size() != n_out) begin
            errors++; $display("MIDI out: %0d bytes, expected %0d", sent.size(), n_out);
        end else
            for (int i = 0; i < n_out; i++)
                if (sent[i] != want[i]) begin
                    errors++;
                    if (errors < 20) $display("MIDI out byte %0d = %0d, expected %0d", i, sent[i], want[i]);
                end
        if (errors == 0 && reads > 0) $display("dev_midi OK (%0d lines, %0d reads, %0d bytes out)", lines, reads, n_out);
        else $display("dev_midi FAILED: %0d errors", errors);
        $finish;
    end
endmodule
