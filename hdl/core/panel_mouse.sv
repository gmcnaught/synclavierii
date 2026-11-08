// The MiSTer mouse (hps_io ps2_mouse: [24] toggles per packet, [7:0]
// buttons and sign bits, [15:8] X movement, [23:16] Y movement, up positive)
// as a pointer on the 640 x 480 screen, and the left button as a press of
// the panel button under the pointer (term_display.sv's panel rows: the
// buttons start at line BUTTON_Y, 8 lines and 40 pixels per button, 16 per
// row, so row r is panel word r). The button stays pressed while the mouse
// button is held.
module panel_mouse #(
    parameter int BUTTON_Y = 408          // first line of the button rows
) (
    input  logic        clk,
    input  logic        rst,
    input  logic [24:0] ps2_mouse,
    output logic [9:0]  x,
    output logic [8:0]  y,
    output logic        moved,            // the mouse has been used (show the pointer)
    output logic        we,               // a panel word changed
    output logic [2:0]  index,
    output logic [15:0] value
);
    logic       toggle_q, held;
    logic [6:0] pbn;
    wire        event_now = ps2_mouse[24] != toggle_q;
    wire        left = ps2_mouse[0];
    wire signed [10:0] dx = {{3{ps2_mouse[4]}}, ps2_mouse[15:8]};
    wire signed [10:0] dy = {{3{ps2_mouse[5]}}, ps2_mouse[23:16]};
    wire signed [11:0] nx = $signed({2'b0, x}) + 12'(dx);
    wire signed [11:0] ny = $signed({3'b0, y}) - 12'(dy);
    wire [9:0]  cx = nx < 0 ? 10'd0 : nx > 12'sd639 ? 10'd639 : 10'(nx);
    wire [8:0]  cy = ny < 0 ? 9'd0 : ny > 12'sd479 ? 9'd479 : 9'(ny);

    // the button under a point, if any
    wire        on_button = cy >= 9'(BUTTON_Y) && cy < 9'(BUTTON_Y + 64);
    wire [8:0]  by = cy - 9'(BUTTON_Y);
    wire [6:0]  hit = {by[5:3], 4'(cx / 10'd40)};

    always_ff @(posedge clk) begin
        we <= 1'b0;
        if (rst) begin
            toggle_q <= ps2_mouse[24];
            x <= 10'd320;
            y <= 9'd240;
            held <= 1'b0;
            moved <= 1'b0;
        end else if (event_now) begin
            toggle_q <= ps2_mouse[24];
            moved <= 1'b1;
            x <= cx;
            y <= cy;
            if (left && !held && on_button) begin            // press
                held <= 1'b1;
                pbn <= hit;
                we <= 1'b1; index <= hit[6:4]; value <= 16'd1 << hit[3:0];
            end else if (!left && held) begin                // release
                held <= 1'b0;
                we <= 1'b1; index <= pbn[6:4]; value <= 16'd0;
            end
        end
    end
endmodule
