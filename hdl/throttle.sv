// Real-time throttle (M4): holds the CPU so that simulated time (the
// devices' time base, 333 ns per bus transfer) tracks real time.
//   debt = simulated ns - real ns, in 1/65536 ns. Each tick adds tick_ns;
//   each clock subtracts 1e9 / CLK_HZ. `stall` while debt > 0: the CPU
//   waits before its next fetch (and before retrying a held read). When the
//   CPU falls behind (debt < 0) it runs free; the credit is capped at
//   CATCHUP_NS so it never races ahead in a long burst. 200 us: a burst of
//   code-cache misses (DDR3 reads) is made up instead of lost; the audio
//   FIFO starts half full (32 samples, 667 us) and covers it.
// `enable` = 0 (simulation, lockstep): never stall.
// `lag_us` counts the real time given up at that cap (the CPU could not keep
// up, e.g. waiting on an SD block): simulated time is that far behind
// real time for good. Shown on the screen for the hardware test.
module throttle #(
    parameter longint CLK_HZ = 50_000_000,
    parameter int CATCHUP_NS = 200_000
) (
    input  logic clk,
    input  logic rst,
    input  logic enable,
    input  logic tick,
    input  logic [9:0] tick_ns,
    output logic stall,
    output logic [31:0] lag_us
);
    localparam longint NS_PER_CLK_Q16 = (64'd1_000_000_000 * 64'd65536) / CLK_HZ;
    localparam longint FLOOR_Q16 = -(64'(CATCHUP_NS) * 64'd65536);

    logic signed [47:0] debt;
    // the tick is taken a clock late and the lost time accumulated a clock
    // after that: real-time accounting only (timing at 50 MHz)
    logic        tick_q;
    logic [9:0]  tick_ns_q;
    wire  signed [47:0] next = debt - 48'(NS_PER_CLK_Q16) + (tick_q ? 48'(tick_ns_q) <<< 16 : 48'sd0);

    assign stall = enable && debt > 48'sd0;

    // given up this clock (< one clock's worth: at most 1 us a clock)
    wire  signed [47:0] lost = next < 48'(FLOOR_Q16) ? 48'(FLOOR_Q16) - next : 48'sd0;
    logic signed [47:0] lost_acc, lost_q;
    wire  signed [47:0] lost_sum = lost_acc + lost_q;
    localparam logic signed [47:0] US_Q16 = 48'sd1000 <<< 16;

    always_ff @(posedge clk) begin
        tick_q <= tick && !rst;
        tick_ns_q <= tick_ns;
        lost_q <= rst ? 48'sd0 : lost;
        if (rst || !enable) debt <= '0;
        else debt <= next < 48'(FLOOR_Q16) ? 48'(FLOOR_Q16) : next;
        if (rst) begin
            lost_acc <= '0;
            lag_us <= '0;
        end else if (lost_sum >= US_Q16) begin
            lost_acc <= lost_sum - US_Q16;
            lag_us <= lag_us + 32'd1;
        end else lost_acc <= lost_sum;
    end
endmodule
