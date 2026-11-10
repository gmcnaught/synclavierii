// Voice time (M14). On the instrument the FM and poly voices run on their
// own clocks; the CPU only writes their registers (D160-D162, D154-D157),
// and a disk load stops the CPU's main loop but never the voices
// (docs/research-log.md §26). In the core every device runs on the CPU's
// simulated time (`cpu_tick`/`cpu_tick_ns`, 333 ns per bus transfer), so
// when the CPU waits in real time (an SD block, a DDR3 burst) the voices
// stop and the audio FIFO runs dry.
//
// With `enable` the voices get their own ticks instead: one tick of 333 ns
// for every 333 ns of the clock (a fractional count of CLK_HZ, in 1/65536
// ns), whatever the CPU is doing. Their 192 kHz sample instants then come
// at exactly 48 kHz x 4 of real time, the rate audio_fifo plays, so the
// FIFO neither fills nor empties. CPU register writes take effect at the
// voice time they arrive at: within the throttle's slack of the simulated
// time they were made at, more after a stall (sim time lags real time by
// lag_us for good). Reads of voice state (D160 bit 0, D157) see voice time,
// so hardware runs no longer repeat sample for sample.
//
// Without `enable` (lockstep, the throttle off) the voices take the CPU's
// ticks as before, so the HDL stays sample for sample with sim/voice.py
// and sim/devices/poly.py.
module voice_clock #(
    parameter longint CLK_HZ = 50_000_000
) (
    input  logic       clk,
    input  logic       rst,
    input  logic       enable,
    input  logic       cpu_tick,
    input  logic [9:0] cpu_tick_ns,
    output logic       tick,
    output logic [9:0] tick_ns
);
    localparam longint NS_PER_CLK_Q16 = (64'd1_000_000_000 * 64'd65536) / CLK_HZ;
    localparam longint TICK_Q16 = 64'd333 * 64'd65536;

    logic [31:0] acc;                       // real ns since the last tick, Q16
    logic        rt_tick;
    wire  [31:0] acc_n = acc + 32'(NS_PER_CLK_Q16);

    always_ff @(posedge clk) begin
        rt_tick <= 1'b0;
        if (rst || !enable) acc <= '0;
        else if (acc_n >= 32'(TICK_Q16)) begin
            acc <= acc_n - 32'(TICK_Q16);
            rt_tick <= 1'b1;
        end else acc <= acc_n;
    end

    assign tick    = enable ? rt_tick && !rst : cpu_tick;
    assign tick_ns = enable ? 10'd333 : cpu_tick_ns;
endmodule
