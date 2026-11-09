// Self-checking test of hdl/core/ps2_ascii.sv (verilator --binary):
// key events as hps_io gives them -> the characters typed.
module ps2_ascii_tb;
    logic        clk = 0, rst = 1, keypad_app = 0;
    logic [10:0] ps2_key = '0;
    logic        valid;
    logic [7:0]  ascii;
    string       got = "";

    ps2_ascii dut (.*);

    always #5 clk = !clk;
    always @(posedge clk) if (valid) got = {got, string'(ascii)};

    task automatic key(input logic ext, input logic [7:0] code, input logic down);
        @(negedge clk);
        ps2_key = {!ps2_key[10], down, ext, code};
        repeat (3) @(negedge clk);
    endtask
    task automatic tap(input logic [7:0] code);
        key(1'b0, code, 1'b1);
        key(1'b0, code, 1'b0);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst = 0;
        // "CATALOG" with shift held, Enter
        key(1'b0, 8'h12, 1'b1);
        tap(8'h21); tap(8'h1c); tap(8'h2c); tap(8'h1c); tap(8'h4b); tap(8'h44); tap(8'h34);
        key(1'b0, 8'h12, 1'b0);
        tap(8'h5a);
        // "cat f1", backspace, right shift + 1 = "!"
        tap(8'h21); tap(8'h1c); tap(8'h2c); tap(8'h29); tap(8'h2b); tap(8'h16); tap(8'h66);
        key(1'b0, 8'h59, 1'b1); tap(8'h16); key(1'b0, 8'h59, 1'b0);
        // Caps Lock: letters upper, digits not; Caps Lock + shift: lower
        tap(8'h58); tap(8'h1c); tap(8'h16);
        key(1'b0, 8'h12, 1'b1); tap(8'h1c); key(1'b0, 8'h12, 1'b0);
        tap(8'h58);
        // Ctrl-C (right Ctrl: extended), keypad Enter, Delete
        key(1'b1, 8'h14, 1'b1); tap(8'h21); key(1'b1, 8'h14, 1'b0);
        key(1'b1, 8'h5a, 1'b1); key(1'b1, 8'h5a, 1'b0);
        key(1'b1, 8'h71, 1'b1); key(1'b1, 8'h71, 1'b0);
        // arrows: up, down, left, right
        key(1'b1, 8'h75, 1'b1); key(1'b1, 8'h75, 1'b0);
        key(1'b1, 8'h72, 1'b1); key(1'b1, 8'h72, 1'b0);
        key(1'b1, 8'h6b, 1'b1); key(1'b1, 8'h6b, 1'b0);
        key(1'b1, 8'h74, 1'b1); key(1'b1, 8'h74, 1'b0);
        // a key with no character (F5) gives nothing; F1, F4 = PF1, PF4
        tap(8'h03);
        tap(8'h05); tap(8'h0c);
        // keypad application mode: keypad Enter = ESC O M, Enter still CR;
        // a key right after it waits for the sequence
        keypad_app = 1;
        @(negedge clk); ps2_key = {!ps2_key[10], 1'b1, 1'b1, 8'h5a};   // keypad Enter
        @(negedge clk); ps2_key = {!ps2_key[10], 1'b1, 1'b0, 8'h1c};   // "a" the next clock
        repeat (5) @(negedge clk);
        key(1'b1, 8'h5a, 1'b0); key(1'b0, 8'h1c, 1'b0);
        tap(8'h5a);
        repeat (4) @(negedge clk);
        if (got != "CATALOG\rcat f1\010!A1a\003\r\177\013\012\010\014\033OP\033OS\033OMa\r") begin
            $display("FAIL: got %p", got);
            $fatal(1);
        end
        $display("ps2_ascii OK");
        $finish;
    end
endmodule
