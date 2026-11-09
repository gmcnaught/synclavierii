// Self-checking test of hdl/core/midi_vpk.sv (verilator --binary): decoded
// MIDI messages -> VPK host ops, with the knob pulse and button tap timing.
// CLK_HZ = 100 kHz: 1 ms = 100 clocks.
module midi_vpk_tb;
    localparam longint HZ = 100_000, MS = HZ / 1000;
    logic       clk = 0, rst = 1;
    logic       msg_valid = 0;
    logic [2:0] msg_kind = 0;
    logic [3:0] msg_chan = 0;
    logic [6:0] msg_m1 = 0, msg_m2 = 0;
    logic       host_we;
    logic [2:0] host_op;
    logic [7:0] host_addr, host_data;
    longint     cyc = 0;

    midi_vpk #(.CLK_HZ(HZ)) dut (.*);

    always #5 clk = !clk;

    logic [18:0] got [$];               // {op, addr, data}
    longint      at [$];
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (host_we) begin
            got.push_back({host_op, host_addr, host_data});
            at.push_back(cyc);
        end
    end

    task automatic msg(input int kind, input int chan, input int m1, input int m2);
        @(negedge clk);
        msg_valid = 1; msg_kind = 3'(kind); msg_chan = 4'(chan); msg_m1 = 7'(m1); msg_m2 = 7'(m2);
        @(negedge clk);
        msg_valid = 0;
        repeat (100) @(negedge clk);     // MIDI bytes are far apart
    endtask

    function automatic logic [18:0] op(input int o, input int a, input int d);
        return {3'(o), 8'(a), 8'(d)};
    endfunction

    int errors = 0;
    task automatic expect_ops(input string what, input logic [18:0] want [$]);
        if (got.size() != want.size()) begin
            $display("FAIL %s: %0d ops, expected %0d", what, got.size(), want.size());
            for (int i = 0; i < got.size(); i++) $display("  got %0d %0d %0d", got[i][18:16], got[i][15:8], got[i][7:0]);
            errors++;
        end else
            for (int i = 0; i < want.size(); i++)
                if (got[i] !== want[i]) begin
                    $display("FAIL %s: op %0d = %0d %0d %0d, expected %0d %0d %0d", what, i,
                             got[i][18:16], got[i][15:8], got[i][7:0],
                             want[i][18:16], want[i][15:8], want[i][7:0]);
                    errors++;
                end
    endtask

    task automatic clear();
        got.delete(); at.delete();
    endtask

    task automatic near(input string what, input longint d, input longint ms);
        if (d < ms * MS - 2 || d > ms * MS + 6) begin
            $display("FAIL %s: %0d clocks, expected %0d ms", what, d, ms);
            errors++;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst = 0;
        // keys: middle C (index 27) with velocity, note off; MIDI 21 folds to 33 (index 0)
        msg(1, 0, 60, 100); msg(0, 0, 60, 0); msg(1, 2, 21, 5); msg(0, 2, 21, 0);
        expect_ops("keys", '{op(0, 27, 100), op(1, 27, 0), op(0, 0, 5), op(1, 0, 0)});
        clear();
        // channel 16 note 5, channel 15 note 3, pad 40 (timb.0), pad 44 (record)
        msg(1, 15, 5, 64); msg(0, 15, 5, 0); msg(1, 14, 3, 64); msg(1, 9, 40, 90); msg(0, 9, 44, 0);
        expect_ops("buttons", '{op(2, 5, 1), op(2, 5, 0), op(2, 131, 1), op(2, 104, 1), op(2, 34, 0)});
        clear();
        // wheels, pedals, breath, ribbon, sustain
        msg(3, 0, 1, 127); msg(3, 0, 1, 0); msg(4, 0, 0, 64); msg(4, 0, 127, 127); msg(4, 0, 0, 0);
        msg(3, 0, 2, 127); msg(3, 0, 4, 0); msg(3, 0, 11, 127); msg(3, 0, 16, 10); msg(3, 0, 64, 127);
        expect_ops("controllers", '{op(3, 5, 193), op(3, 5, 13), op(3, 4, 128), op(3, 4, 223), op(3, 4, 32),
                                    op(3, 6, 245), op(3, 3, 235), op(3, 2, 10), op(3, 1, 38), op(4, 0, 8)});
        clear();
        // pressure: key pressure on a held key; channel pressure on every held key
        msg(1, 0, 60, 100); msg(1, 0, 64, 100); msg(5, 0, 60, 50); msg(6, 0, 40, 0);
        expect_ops("pressure", '{op(0, 27, 100), op(0, 31, 100), op(5, 27, 100), op(5, 27, 80), op(5, 31, 80)});
        clear();
        // all notes off releases them
        msg(3, 0, 123, 0);
        expect_ops("all notes off", '{op(1, 27, 0), op(1, 31, 0)});
        clear();
        // pot 1: first message sets the base; +1 -> one 1-step pulse; then -5 (fast: x4 = -20)
        msg(3, 0, 21, 64); msg(3, 0, 21, 65);
        repeat (60 * MS) @(negedge clk);
        expect_ops("knob +1", '{op(3, 0, 168), op(3, 0, 128)});
        near("knob hold", at[1] - at[0], 20);
        clear();
        msg(3, 0, 21, 60);
        repeat (400 * MS) @(negedge clk);
        expect_ops("knob -20", '{op(3, 0, 62), op(3, 0, 128), op(3, 0, 62), op(3, 0, 128),
                                 op(3, 0, 67), op(3, 0, 128), op(3, 0, 88), op(3, 0, 128)});
        near("knob gap", at[2] - at[1], 30);
        clear();
        // pot 2 (partial volume, PBN 17): press it, then the step
        msg(3, 0, 22, 10); msg(3, 0, 22, 11);
        repeat (400 * MS) @(negedge clk);
        expect_ops("pot 2", '{op(2, 17, 1), op(2, 17, 0), op(3, 0, 168), op(3, 0, 128)});
        near("tap hold", at[1] - at[0], 100);
        near("tap gap", at[2] - at[1], 200);
        clear();
        // same pot again: no new press
        msg(3, 0, 22, 12);
        repeat (100 * MS) @(negedge clk);
        expect_ops("pot 2 again", '{op(3, 0, 168), op(3, 0, 128)});
        clear();
        // program change 11: BANK, timb.1, ENTRY, timb.3; 1.5 s after the bank number
        msg(2, 0, 11, 0);
        repeat (2600 * MS) @(negedge clk);
        expect_ops("program", '{op(2, 97, 1), op(2, 97, 0), op(2, 105, 1), op(2, 105, 0),
                                op(2, 98, 1), op(2, 98, 0), op(2, 107, 1), op(2, 107, 0)});
        if (got.size() == 8) begin
            near("bank gap", at[2] - at[1], 200);
            near("bank number gap", at[4] - at[3], 1500);
            near("entry gap", at[6] - at[5], 200);
        end
        if (errors != 0) $fatal(1);
        $display("midi_vpk OK");
        $finish;
    end
endmodule
