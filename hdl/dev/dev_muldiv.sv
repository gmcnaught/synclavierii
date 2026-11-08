// D4567 multiply/divide (sim/devices/muldiv.py), unsigned.
//   write D4: D4 = v            write D5: D5 = v, D4 = 0
//   write D6: D5:D4 <- D5 * v + D4 (low word in D5, high in D4)
//   write D7: (D4:D5) / v -> D5 = quotient low word, D4 = remainder + quotient
//             high word (as NED's XPL.h); v = 0: D4 = old D5, D5 = 177777
//   read D4, D5; reading D6/D7 has no SYN.
// The divide takes 33 clocks; reads and writes wait (no SYN yet) until it
// is done. That costs no simulated time: Python's divide is instant.
module dev_muldiv (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,          // D4-D7 addressed (rd or wr)
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D4, 1 D5, 2 D6, 3 D7
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        nosyn,
    input  logic        ld_we,        // state load (simulation): 0 D4, 1 D5
    input  logic [3:0]  ld_addr,
    input  logic [31:0] ld_data
);
    logic [15:0] d4, d5;
    logic [5:0]  count;               // divide steps left
    logic [31:0] quo;
    logic [15:0] rem;
    logic [15:0] divisor;

    wire busy = count != 6'd0;
    assign nosyn = sel && rd && reg_sel[1];
    assign ack   = sel && !busy && !nosyn;
    assign rdata = reg_sel[0] ? d5 : d4;

    wire [31:0] product = d5 * wdata + {16'd0, d4};
    // restoring division, one quotient bit per clock
    wire [16:0] trial    = {rem[15:0], quo[31]};
    wire        fits     = trial >= {1'b0, divisor};
    wire [16:0] rem_next = fits ? trial - {1'b0, divisor} : trial;
    wire [31:0] quo_next = {quo[30:0], fits};

    always_ff @(posedge clk) begin
        if (rst) begin
            count <= 6'd0;
            if (ld_we && ld_addr == 4'd0) d4 <= ld_data[15:0];
            if (ld_we && ld_addr == 4'd1) d5 <= ld_data[15:0];
        end else if (busy) begin
            rem <= rem_next[15:0];
            quo <= quo_next;
            count <= count - 6'd1;
            if (count == 6'd1) begin                    // last step: results
                d5 <= quo_next[15:0];
                d4 <= quo_next[31:16] + rem_next[15:0];
            end
        end else if (ack && wr) begin
            case (reg_sel)
                2'd0: d4 <= wdata;
                2'd1: begin d5 <= wdata; d4 <= 16'd0; end
                2'd2: begin d5 <= product[15:0]; d4 <= product[31:16]; end
                default:
                    if (wdata == 16'd0) begin
                        d4 <= d5;
                        d5 <= 16'hFFFF;
                    end else begin
                        quo <= {d4, d5};
                        rem <= 16'd0;
                        divisor <= wdata;
                        count <= 6'd32;
                    end
            endcase
        end
    end
endmodule
