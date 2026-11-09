// D44/D45 mouse port of the D40Q card and D54, its interrupt bits
// (sim/devices/mouse.py; docs/devices/vt640-graphics-terminal.md 6.5):
//   D44 write: P (0120) -> a 3-byte position report, s (0163) -> O (0117);
//              other bytes no reply. D44 read: the received byte, clears
//              receive-ready.
//   D45 read: bit 1 receive-ready. D45 write: accepted (keeps receive-ready).
//   D54 write: interrupt enables (bit 2 = D44). D54 read: enables & ready.
//   irq (PSW bit 10) while D44's interrupt is enabled and a byte is ready.
// Report: 0200 | X sign 020 (1 = right) | Y sign 010 (1 = up) | left 4 |
// middle 2 | right 1, then |dX|, |dY| (0-127) of the motion since the last
// report (the rest is kept). Reply bytes arrive one per 1 ms of simulated
// time (tick/tick_ns), the first 1 ms after the command.
// Host: host_we adds (host_dx, host_dy) (up = +) and sets the buttons.
module dev_mouse (
    input  logic        clk,
    input  logic        rst,
    input  logic        tick,
    input  logic [9:0]  tick_ns,

    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D44, 1 D45, 2 D54
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        irq,

    input  logic        host_we,
    input  logic signed [7:0] host_dx,
    input  logic signed [7:0] host_dy,
    input  logic [2:0]  host_buttons  // {left, middle, right}
);
    localparam logic [31:0] BYTE_NS = 32'd1_000_000;

    logic signed [15:0] ax, ay;           // motion not yet reported
    logic [2:0]  buttons;
    logic [7:0]  q0, q1, q2;              // reply bytes still to arrive, q0 first
    logic [1:0]  qn;
    logic [31:0] due;                     // ns until the next one arrives
    logic [7:0]  rx;
    logic        ready;
    logic [2:0]  enables;

    wire signed [15:0] cx = ax > 16'sd127 ? 16'sd127 : ax < -16'sd127 ? -16'sd127 : ax;
    wire signed [15:0] cy = ay > 16'sd127 ? 16'sd127 : ay < -16'sd127 ? -16'sd127 : ay;
    wire [7:0] r0 = 8'o200 | (cx >= 0 ? 8'o20 : 8'd0) | (cy >= 0 ? 8'o10 : 8'd0) | {5'd0, buttons};
    wire [7:0] r1 = 8'(cx >= 0 ? cx : -cx);
    wire [7:0] r2 = 8'(cy >= 0 ? cy : -cy);

    assign ack = sel;
    assign irq = enables[2] && ready;
    always_comb
        case (reg_sel)
            2'd0:    rdata = {8'd0, rx};
            2'd1:    rdata = {14'd0, ready, 1'b0};
            default: rdata = {13'd0, enables & {ready, 2'b00}};
        endcase

    wire acc_wr = sel && wr;
    wire [7:0] cmd = wdata[7:0];
    always_ff @(posedge clk) begin
        if (rst) begin
            ax <= '0; ay <= '0; buttons <= '0; qn <= '0; due <= '0;
            rx <= '0; ready <= 1'b0; enables <= '0;
        end else begin
            if (host_we) begin
                ax <= ax + 16'(host_dx);
                ay <= ay + 16'(host_dy);
                buttons <= host_buttons;
            end
            if (sel && rd && reg_sel == 2'd0) ready <= 1'b0;
            if (acc_wr && reg_sel == 2'd2) enables <= wdata[2:0];
            if (acc_wr && reg_sel == 2'd0 && (cmd == 8'o120 || cmd == 8'o163)) begin
                // queue the reply behind any bytes still to come
                if (qn == 2'd0) due <= BYTE_NS;
                if (cmd == 8'o120) begin
                    ax <= ax - cx + (host_we ? 16'(host_dx) : 16'sd0);
                    ay <= ay - cy + (host_we ? 16'(host_dy) : 16'sd0);
                    case (qn)
                        2'd0: begin q0 <= r0; q1 <= r1; q2 <= r2; end
                        default: ;            // a report while one is arriving: dropped
                    endcase
                    if (qn == 2'd0) qn <= 2'd3;
                end else begin
                    case (qn)
                        2'd0: q0 <= 8'o117;
                        2'd1: q1 <= 8'o117;
                        2'd2: q2 <= 8'o117;
                        default: ;
                    endcase
                    if (qn != 2'd3) qn <= qn + 2'd1;
                end
            end else if (tick && qn != 2'd0) begin
                if (32'(tick_ns) >= due) begin
                    rx <= q0; ready <= 1'b1;
                    q0 <= q1; q1 <= q2;
                    qn <= qn - 2'd1;
                    due <= due + BYTE_NS - 32'(tick_ns);
                end else due <= due - 32'(tick_ns);
            end
        end
    end
endmodule
