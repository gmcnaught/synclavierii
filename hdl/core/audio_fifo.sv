// Audio to real time: pcm_out's 48 kHz samples arrive as the CPU makes
// simulated time (every 1/48000 s of it, give or take the throttle's slack:
// up to CATCHUP_NS plus an instruction); this FIFO plays them at a steady
// 48 kHz from the clock (a fractional divider: CLK_HZ / 48000 clocks a
// sample on average). Playback starts once half full; when the FIFO runs dry
// (the CPU fell behind real time) the last sample is held and playback
// waits until it is half full again; when full, incoming samples are
// dropped. `underruns` and `overruns` count those events.
module audio_fifo #(
    parameter longint CLK_HZ = 16_000_000,
    parameter longint RATE = 48_000,
    parameter int DEPTH_BITS = 6
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        in_valid,
    input  logic signed [15:0] in_l,
    input  logic signed [15:0] in_r,
    output logic signed [15:0] out_l,
    output logic signed [15:0] out_r,
    output logic        out_strobe,       // a sample left the FIFO (or was held)
    output logic [15:0] underruns,
    output logic [15:0] overruns
);
    localparam int N = 1 << DEPTH_BITS;
    localparam int AW = $clog2(CLK_HZ + RATE);

    logic [31:0] mem [N];
    logic [DEPTH_BITS-1:0] wp, rp;
    logic [DEPTH_BITS:0]   count;
    logic        playing;
    logic [AW-1:0] acc;

    wire tick = acc >= AW'(CLK_HZ - RATE);           // acc + RATE >= CLK_HZ
    wire full = count == (DEPTH_BITS + 1)'(N);
    wire pop  = tick && playing && count != '0;
    wire push = in_valid && !full;

    always_ff @(posedge clk) begin
        out_strobe <= 1'b0;
        if (rst) begin
            wp <= '0; rp <= '0; count <= '0;
            playing <= 1'b0;
            acc <= '0;
            out_l <= '0; out_r <= '0;
            underruns <= '0; overruns <= '0;
        end else begin
            acc <= tick ? acc + AW'(RATE) - AW'(CLK_HZ) : acc + AW'(RATE);
            if (push) begin
                mem[wp] <= {in_l, in_r};
                wp <= wp + 1'b1;
            end
            if (in_valid && full) overruns <= overruns + 16'd1;
            if (pop) begin
                {out_l, out_r} <= mem[rp];
                rp <= rp + 1'b1;
            end
            count <= count + (DEPTH_BITS + 1)'(push) - (DEPTH_BITS + 1)'(pop);
            if (tick) begin
                out_strobe <= 1'b1;
                if (playing && count == '0) begin
                    playing <= 1'b0;
                    underruns <= underruns + 16'd1;
                end
            end
            if (!playing && count >= (DEPTH_BITS + 1)'(N / 2)) playing <= 1'b1;
        end
    end
endmodule
