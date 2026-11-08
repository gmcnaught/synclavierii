// MiSTer ps2_key events (hps_io: [10] toggles per event, [9] pressed,
// [8] extended, [7:0] set-2 scan code) to ASCII for the system terminal,
// US layout. Shift, Caps Lock (letters only) and Ctrl (letter & 037) are
// applied; Enter = CR, Backspace = BS (MONITOR also takes DEL and ^Z:
// MONCAT 04-IOMOD), Tab = HT, Esc = ESC, Delete = DEL. The arrow keys send
// the codes the real-time program maps arrows to (NED SYNLITS:ASCIILIT
// U.ARR/D.ARR/L.ARR/R.ARR, as an ADM-3A sends them): up ^K, down ^J,
// left ^H, right ^L. One character per key press, the clock after the event.
module ps2_ascii (
    input  logic        clk,
    input  logic        rst,
    input  logic [10:0] ps2_key,
    output logic        valid,
    output logic [7:0]  ascii
);
    logic toggle_q, shift_l, shift_r, ctrl, caps;

    // {unshifted, shifted}; 0 = no character
    function automatic logic [15:0] keymap(input logic ext, input logic [7:0] code);
        keymap = 16'd0;
        if (ext) begin
            case (code)
                8'h5a: keymap = {8'o015, 8'o015};    // keypad Enter
                8'h71: keymap = {8'o177, 8'o177};    // Delete
                8'h4a: keymap = {"/", "/"};          // keypad /
                8'h75: keymap = {8'o013, 8'o013};    // up    (U.ARR)
                8'h72: keymap = {8'o012, 8'o012};    // down  (D.ARR)
                8'h6b: keymap = {8'o010, 8'o010};    // left  (L.ARR)
                8'h74: keymap = {8'o014, 8'o014};    // right (R.ARR)
                default: ;
            endcase
        end else begin
            case (code)
                8'h1c: keymap = {"a", "A"}; 8'h32: keymap = {"b", "B"}; 8'h21: keymap = {"c", "C"};
                8'h23: keymap = {"d", "D"}; 8'h24: keymap = {"e", "E"}; 8'h2b: keymap = {"f", "F"};
                8'h34: keymap = {"g", "G"}; 8'h33: keymap = {"h", "H"}; 8'h43: keymap = {"i", "I"};
                8'h3b: keymap = {"j", "J"}; 8'h42: keymap = {"k", "K"}; 8'h4b: keymap = {"l", "L"};
                8'h3a: keymap = {"m", "M"}; 8'h31: keymap = {"n", "N"}; 8'h44: keymap = {"o", "O"};
                8'h4d: keymap = {"p", "P"}; 8'h15: keymap = {"q", "Q"}; 8'h2d: keymap = {"r", "R"};
                8'h1b: keymap = {"s", "S"}; 8'h2c: keymap = {"t", "T"}; 8'h3c: keymap = {"u", "U"};
                8'h2a: keymap = {"v", "V"}; 8'h1d: keymap = {"w", "W"}; 8'h22: keymap = {"x", "X"};
                8'h35: keymap = {"y", "Y"}; 8'h1a: keymap = {"z", "Z"};
                8'h16: keymap = {"1", "!"}; 8'h1e: keymap = {"2", "@"}; 8'h26: keymap = {"3", "#"};
                8'h25: keymap = {"4", "$"}; 8'h2e: keymap = {"5", "%"}; 8'h36: keymap = {"6", "^"};
                8'h3d: keymap = {"7", "&"}; 8'h3e: keymap = {"8", "*"}; 8'h46: keymap = {"9", "("};
                8'h45: keymap = {"0", ")"};
                8'h0e: keymap = {"`", "~"}; 8'h4e: keymap = {"-", "_"}; 8'h55: keymap = {"=", "+"};
                8'h54: keymap = {"[", "{"}; 8'h5b: keymap = {"]", "}"}; 8'h5d: keymap = {8'h5c, "|"};    // backslash (hex: Quartus 17 strings)
                8'h4c: keymap = {";", ":"}; 8'h52: keymap = {"'", 8'h22}; 8'h41: keymap = {",", "<"};
                8'h49: keymap = {".", ">"}; 8'h4a: keymap = {"/", "?"};
                8'h29: keymap = {" ", " "};
                8'h5a: keymap = {8'o015, 8'o015};    // Enter
                8'h66: keymap = {8'o010, 8'o010};    // Backspace
                8'h0d: keymap = {8'o011, 8'o011};    // Tab
                8'h76: keymap = {8'o033, 8'o033};    // Esc
                // keypad digits and point (Num Lock assumed on)
                8'h70: keymap = {"0", "0"}; 8'h69: keymap = {"1", "1"}; 8'h72: keymap = {"2", "2"};
                8'h7a: keymap = {"3", "3"}; 8'h6b: keymap = {"4", "4"}; 8'h73: keymap = {"5", "5"};
                8'h74: keymap = {"6", "6"}; 8'h6c: keymap = {"7", "7"}; 8'h75: keymap = {"8", "8"};
                8'h7d: keymap = {"9", "9"}; 8'h71: keymap = {".", "."}; 8'h7c: keymap = {"*", "*"};
                8'h7b: keymap = {"-", "-"}; 8'h79: keymap = {"+", "+"};
                default: ;
            endcase
        end
    endfunction

    wire        event_now = ps2_key[10] != toggle_q;
    wire        pressed   = ps2_key[9];
    wire        ext       = ps2_key[8];
    wire [7:0]  code      = ps2_key[7:0];
    wire [15:0] m         = keymap(ext, code);
    wire        letter    = m[7:0] >= "A" && m[7:0] <= "Z";
    wire        shifted   = (shift_l || shift_r) ^ (caps && letter);
    wire [7:0]  ch        = shifted ? m[7:0] : m[15:8];

    always_ff @(posedge clk) begin
        valid <= 1'b0;
        if (rst) begin
            toggle_q <= ps2_key[10];
            shift_l <= 1'b0; shift_r <= 1'b0; ctrl <= 1'b0; caps <= 1'b0;
        end else if (event_now) begin
            toggle_q <= ps2_key[10];
            if (!ext && code == 8'h12) shift_l <= pressed;
            else if (!ext && code == 8'h59) shift_r <= pressed;
            else if (code == 8'h14) ctrl <= pressed;           // left or right
            else if (!ext && code == 8'h58) begin if (pressed) caps <= !caps; end
            else if (pressed && ch != 8'd0) begin
                valid <= 1'b1;
                ascii <= ctrl && letter ? (m[7:0] & 8'o037) : ch;
            end
        end
    end
endmodule
