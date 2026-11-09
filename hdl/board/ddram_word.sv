// 16-bit word port (synclavier_core xr_*) on MiSTer's DDR3 port (DDRAM_*,
// Avalon-MM, 64-bit, burst 1). Word w lives at byte BASE + 2w; DDR3 from
// 0x30000000 is free for cores. `wide` with wr writes wdata to the 512
// words from w (a multiple of 512): one burst of 128 64-bit beats (poly
// memory clear).
//
// Handshake as the simulation RAM models: hold rd/wr until ack, a
// one-clock pulse with rdata valid; the clock after an ack is ignored. A
// write is acknowledged when the controller accepts it (Avalon keeps the
// order, so a later read sees it).
module ddram_word #(
    parameter logic [31:0] BASE = 32'h3000_0000
) (
    input  logic        clk,
    input  logic        rst,

    input  logic [26:0] addr,          // words: 256 MB from BASE
    input  logic        rd,
    input  logic        wr,
    input  logic        wide,
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,

    input  logic        DDRAM_BUSY,
    output logic [7:0]  DDRAM_BURSTCNT,
    output logic [28:0] DDRAM_ADDR,
    input  logic [63:0] DDRAM_DOUT,
    input  logic        DDRAM_DOUT_READY,
    output logic        DDRAM_RD,
    output logic [63:0] DDRAM_DIN,
    output logic [7:0]  DDRAM_BE,
    output logic        DDRAM_WE
);
    localparam logic [28:0] BASE_Q = 29'(BASE >> 3);

    localparam logic [1:0] S_IDLE = 2'd0, S_CMD = 2'd1, S_DATA = 2'd2, S_BURST = 2'd3;
    logic [1:0] state;
    logic [1:0] lane;
    logic [6:0] beat;
    logic       burst;

    assign DDRAM_BURSTCNT = burst ? 8'd128 : 8'd1;

    always_ff @(posedge clk) begin
        ack <= 1'b0;
        if (rst) begin
            state <= S_IDLE;
            DDRAM_RD <= 1'b0;
            DDRAM_WE <= 1'b0;
            burst <= 1'b0;
        end else case (state)
            S_IDLE:
                if ((rd || wr) && !ack) begin
                    DDRAM_ADDR <= BASE_Q + 29'(addr[26:2]);
                    DDRAM_DIN  <= {4{wdata}};
                    DDRAM_BE   <= wide ? 8'hFF : 8'b0000_0011 << {addr[1:0], 1'b0};
                    DDRAM_RD   <= rd;
                    DDRAM_WE   <= wr;
                    lane <= addr[1:0];
                    burst <= wr && wide;
                    beat <= '0;
                    state <= wr && wide ? S_BURST : S_CMD;
                end
            S_BURST:                             // one beat per accepted clock
                if (!DDRAM_BUSY) begin
                    beat <= beat + 7'd1;
                    if (beat == 7'd127) begin
                        DDRAM_WE <= 1'b0;
                        burst <= 1'b0;
                        ack <= 1'b1;
                        state <= S_IDLE;
                    end
                end
            S_CMD:                               // held until accepted
                if (!DDRAM_BUSY) begin
                    DDRAM_RD <= 1'b0;
                    DDRAM_WE <= 1'b0;
                    if (DDRAM_WE) begin
                        ack <= 1'b1;
                        state <= S_IDLE;
                    end else state <= S_DATA;
                end
            S_DATA:
                if (DDRAM_DOUT_READY) begin
                    rdata <= DDRAM_DOUT[{lane, 4'd0} +: 16];
                    ack <= 1'b1;
                    state <= S_IDLE;
                end
            default: state <= S_IDLE;
        endcase
    end
endmodule
