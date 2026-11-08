// D3 real-time clock (sim/devices/rtc.py): a request every 5 ms (200 Hz),
// PSW bit 8. Read: 1 while a tick is pending; write: clear it. Missed
// ticks coalesce into one request.
module dev_rtc #(
    parameter int PERIOD_NS = 5_000_000
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        acc,          // read or write completes this clock
    input  logic        wr,
    output logic [15:0] rdata,
    input  logic        tick,
    input  logic [9:0]  tick_ns,
    output logic        irq,
    input  logic        ld_we,        // state load (simulation): 0 elapsed, 1 pending
    input  logic [3:0]  ld_addr,
    input  logic [31:0] ld_data
);
    logic [31:0] elapsed;
    logic        pending;

    assign rdata = {15'd0, pending};
    assign irq   = pending;

    wire [31:0] next = elapsed + {22'd0, tick_ns};

    always_ff @(posedge clk) begin
        if (rst) begin
            if (ld_we && ld_addr == 4'd0) elapsed <= ld_data;
            if (ld_we && ld_addr == 4'd1) pending <= ld_data[0];
        end else if (acc && wr) begin
            pending <= 1'b0;
        end else if (tick) begin
            if (next >= PERIOD_NS) begin
                elapsed <= next - PERIOD_NS;
                pending <= 1'b1;
            end else
                elapsed <= next;
        end
    end
endmodule
