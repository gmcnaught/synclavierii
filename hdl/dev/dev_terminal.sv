// D50/D51 system terminal (sim/devices/terminal.py).
//   D50 read: the received character; held (`hold`, Python's BUS_WAIT)
//             while none is present. D50 write: send a character.
//   D51 read: status = device-present bits | 4 XMIT_MT | 2 CHAR_RDY |
//             1 XMIT_IRQ. D51 write: clear XMIT_IRQ; bit 15 sets the baud
//             rate from bits 10-8 (300 ... 76800).
//   Interrupt (PSW bit 6) while CHAR_RDY or XMIT_IRQ.
// Character time = 10 bits at the baud rate, in the CPU's simulated time.
// Host input goes into a FIFO; a character moves to the receiver as soon
// as it is empty and the previous character's time has passed (Python
// receives eagerly: on input, after a D50 read and after every tick).
module dev_terminal #(
    parameter int FIFO_BITS = 8
) (
    input  logic        clk,
    input  logic        rst,
    input  logic [15:0] device_bits,  // D51 device-present bits 15-8 (e.g. 1000 = D60)
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic        reg_sel,      // 0 D50, 1 D51
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        hold,
    input  logic        tick,
    input  logic [9:0]  tick_ns,
    output logic        irq,

    input  logic        host_rx_valid,    // host keyboard byte into the FIFO
    input  logic [7:0]  host_rx_data,
    output logic        host_tx_valid,    // byte sent by the program
    output logic [7:0]  host_tx_data,

    input  logic        ld_we,        // state load (simulation): 0 baud index,
    input  logic [3:0]  ld_addr,      // 1 rx char, 2 char_rdy, 3 rx_wait,
    input  logic [31:0] ld_data       // 4 tx_busy, 5 xmit_irq
);
    logic [2:0]  baud;
    logic [7:0]  rx_char;
    logic        char_rdy, xmit_irq;
    logic signed [31:0] rx_wait, tx_busy;

    logic [7:0]  fifo [1 << FIFO_BITS];
    logic [FIFO_BITS-1:0] head, tail;
    wire fifo_any = head != tail;

    logic signed [31:0] char_ns;
    always_comb begin
        case (baud)     // round(10e9 / baud)
            3'd0: char_ns = 33_333_333;
            3'd1: char_ns = 8_333_333;
            3'd2: char_ns = 4_166_667;
            3'd3: char_ns = 2_083_333;
            3'd4: char_ns = 1_041_667;
            3'd5: char_ns = 520_833;
            3'd6: char_ns = 260_417;
            default: char_ns = 130_208;
        endcase
    end

    // receiver as Python sees it after an eager _receive()
    wire        recv_now = !char_rdy && fifo_any && rx_wait <= 0;
    wire        rdy_eff  = char_rdy || recv_now;
    wire [7:0]  char_eff = char_rdy ? rx_char : fifo[head];
    wire signed [31:0] wait_eff = recv_now ? char_ns : rx_wait;

    assign rdata = reg_sel ? ((device_bits & 16'hFF00) | {13'd0, tx_busy <= 0, rdy_eff, xmit_irq})
                           : {8'd0, char_eff};
    assign ack   = sel && (reg_sel || wr || rdy_eff);
    assign hold  = sel && rd && !reg_sel && !rdy_eff;
    assign irq   = rdy_eff || xmit_irq;
    assign host_tx_valid = sel && wr && !reg_sel;
    assign host_tx_data  = wdata[7:0];

    wire signed [31:0] ns = {22'd0, tick_ns};

    always_ff @(posedge clk) begin
        if (rst) begin
            head <= '0;
            tail <= '0;
            if (ld_we) case (ld_addr)
                4'd0: baud <= ld_data[2:0];
                4'd1: rx_char <= ld_data[7:0];
                4'd2: char_rdy <= ld_data[0];
                4'd3: rx_wait <= ld_data;
                4'd4: tx_busy <= ld_data;
                4'd5: xmit_irq <= ld_data[0];
                default: ;
            endcase
        end else begin
            if (host_rx_valid) begin
                fifo[tail] <= host_rx_data;
                tail <= tail + 1'b1;
            end
            // commit the eager receive
            if (recv_now) begin
                rx_char <= fifo[head];
                char_rdy <= 1'b1;
                head <= head + 1'b1;
            end
            rx_wait <= wait_eff;
            if (sel && ack && rd && !reg_sel) begin
                char_rdy <= 1'b0;                     // character taken
            end else if (sel && ack && wr) begin
                xmit_irq <= 1'b0;
                if (reg_sel) begin
                    if (wdata[15]) baud <= wdata[10:8];
                end else
                    tx_busy <= char_ns;
            end else if (tick) begin
                if (tx_busy > 0) begin
                    tx_busy <= tx_busy - ns;
                    if (tx_busy - ns <= 0) xmit_irq <= 1'b1;
                end
                if (wait_eff > 0) rx_wait <= wait_eff - ns;
            end
        end
    end
endmodule
