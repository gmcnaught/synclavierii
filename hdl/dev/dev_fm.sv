// D160-D163 FM interface (sim/devices/synth.py FMInterface, sim/fm.py).
//   D160 write: channel word (low 8 bits = channel); D161 write: function;
//   D162 write: data to (channel, function). D163 write: 1 toggles the
//   external clock output, xxx10 selects A/D channel bits 4-2.
//   D160 read: switches (bits 7-2) | external clock in (bit 1) | bit 0 =
//     channel present (channel < 2 x VOICES), cleared while function 12 is
//     selected and the channel's interpolator is at its limit.
//   D163 read: the selected A/D value. D161/D162 reads: no SYN when strict.
// Per channel: pitch (0 INC, 1 NNU, 2 ONU), TIM (4), function 13 (ISHC /
// VOL), the interpolator (10 divisor, 11 adder, 12 limit) and a wave
// memory address (6 zero, 7 store byte + increment) into 32 x 256 bytes.
// The interpolators run at 192 kHz of simulated time (tick/tick_ns:
// 192000 / 1e9 = 24 / 125000 clocks per ns), one clock at a time with the
// closed form of sim/fm.py Interpolator.advance_to.
module dev_fm #(
    parameter int VOICES = 8
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0-3: D160-D163
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        nosyn,
    input  logic        strict,
    input  logic        tick,
    input  logic [9:0]  tick_ns,

    // voice engine side: per-channel registers and the wave memory
    output logic [7:0]  ch_inc [2*VOICES],
    output logic [7:0]  ch_nnu [2*VOICES],
    output logic [7:0]  ch_onu [2*VOICES],
    output logic [7:0]  ch_tim [2*VOICES],
    output logic [7:0]  ch_f13 [2*VOICES],
    output logic [7:0]  ch_env [2*VOICES],      // interpolator value
    output logic [7:0]  ch_env_next [2*VOICES], // ... after an interpolator clock now
    output logic [17:0] fm_rem,                 // interpolator clock phase
    input  logic        hold,                   // voice engine mixing: accesses wait
    input  logic [12:0] wave_addr,              // {memory, point}
    output logic [7:0]  wave_q,
    output logic        interp_clock,           // an interpolator clock this edge

    input  logic        ld_we,        // state load (simulation), see sim/lockstep.py
    input  logic        ld_wave,      // ld_addr = wave memory address
    input  logic [12:0] ld_addr,
    input  logic [31:0] ld_data
);
    localparam int NCH = 2 * VOICES;

    logic [15:0] channel_word, function_;
    logic [7:0]  switches;
    logic        ext_in, ext_out;
    logic [15:0] adc [8];
    logic [2:0]  adc_select;
    logic [17:0] rem;                           // (time x 24) mod 125000 (< 2^17)

    logic [7:0]  div [NCH], add [NCH], lim [NCH], val [NCH], pre [NCH], acc [NCH], mar [NCH];
    logic [7:0]  wave [8192] /* verilator public */;   // public: board bench reads it

    wire [7:0] ch = channel_word[7:0];
    wire       ch_ok = {8'd0, ch} < 16'(NCH);
    wire [3:0] c = ch[3:0];

    // -------------------------------------------------------------- reads
    wire bit0 = ch_ok && !(function_ == 16'o12 && val[c] == lim[c]);
    assign nosyn = sel && rd && strict && (reg_sel == 2'd1 || reg_sel == 2'd2);
    assign ack   = sel && !nosyn && !hold;
    always_comb begin
        case (reg_sel)
            2'd0: rdata = {8'd0, switches & 8'o374} | {14'd0, ext_in, bit0};
            2'd3: rdata = adc[adc_select];
            default: rdata = 16'd0;
        endcase
    end

    // --------------------------------------------------- interpolator clock
    wire [17:0] rem_next = rem + 18'(tick_ns) * 18'd24;    // up to 148,975: 18 bits
    assign interp_clock = tick && rem_next >= 18'd125000;

    // one clock of every interpolator (closed form for n = 1)
    logic [7:0] pre_n [NCH], acc_n [NCH], val_n [NCH];
    always_comb begin
        for (int k = 0; k < NCH; k++) begin
            logic [8:0]  d, total, pulses;
            logic [16:0] sum;
            logic [8:0]  steps;
            d      = 9'd256 - {1'b0, div[k]};
            total  = {1'b0, pre[k]} + 9'd1;
            pulses = total / d;
            pre_n[k] = 8'(total % d);
            sum    = {8'd0, acc[k]} + 17'(pulses) * (17'(add[k]) + 17'd1);
            steps  = sum[16:8];
            acc_n[k] = pulses == 9'd0 ? acc[k] : sum[7:0];
            if (val[k] < lim[k])
                val_n[k] = 9'(val[k]) + steps >= 9'(lim[k]) ? lim[k] : val[k] + steps[7:0];
            else if (val[k] > lim[k])
                val_n[k] = 9'(lim[k]) + steps >= 9'(val[k]) ? lim[k] : val[k] - steps[7:0];
            else
                val_n[k] = val[k];
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            if (ld_we && ld_wave) wave[ld_addr] <= ld_data[7:0];
            else if (ld_we) begin
                if (ld_addr < 13'd32) case (ld_addr[4:0])
                    5'd0: channel_word <= ld_data[15:0];
                    5'd1: function_ <= ld_data[15:0];
                    5'd2: switches <= ld_data[7:0];
                    5'd3: ext_in <= ld_data[0];
                    5'd4: ext_out <= ld_data[0];
                    5'd5: adc_select <= ld_data[2:0];
                    5'd6: rem <= ld_data[17:0];
                    default: if (ld_addr[4:3] == 2'd1) adc[ld_addr[2:0]] <= ld_data[15:0];
                endcase
                else begin
                    automatic logic [3:0] k = ld_addr[7:4] - 4'd2;
                    case (ld_addr[3:0])
                        4'd0: div[k] <= ld_data[7:0];
                        4'd1: add[k] <= ld_data[7:0];
                        4'd2: lim[k] <= ld_data[7:0];
                        4'd3: val[k] <= ld_data[7:0];
                        4'd4: pre[k] <= ld_data[7:0];
                        4'd5: acc[k] <= ld_data[7:0];
                        4'd6: mar[k] <= ld_data[7:0];
                        4'd7: {ch_inc[k], ch_nnu[k], ch_onu[k], ch_tim[k]} <= ld_data;
                        4'd8: ch_f13[k] <= ld_data[7:0];
                        default: ;
                    endcase
                end
            end
        end else begin
            if (tick) rem <= interp_clock ? rem_next - 18'd125000 : rem_next;
            if (interp_clock)
                for (int k = 0; k < NCH; k++) begin
                    pre[k] <= pre_n[k];
                    acc[k] <= acc_n[k];
                    val[k] <= val_n[k];
                end
            if (ack && wr) begin
                case (reg_sel)
                    2'd0: channel_word <= wdata;
                    2'd1: function_ <= wdata;
                    2'd2: if (ch_ok) begin
                        case (function_)
                            16'o0:  ch_inc[c] <= wdata[7:0];
                            16'o1:  ch_nnu[c] <= wdata[7:0];
                            16'o2:  ch_onu[c] <= wdata[7:0];
                            16'o4:  ch_tim[c] <= wdata[7:0];
                            16'o6:  mar[c] <= 8'd0;
                            16'o7: begin
                                wave[{ch_tim[c][4:0], mar[c]}] <= wdata[7:0];
                                mar[c] <= mar[c] + 8'd1;
                            end
                            16'o10: div[c] <= wdata[7:0];
                            16'o11: add[c] <= wdata[7:0];
                            16'o12: lim[c] <= wdata[7:0];
                            16'o13: ch_f13[c] <= wdata[7:0];
                            default: ;
                        endcase
                    end
                    default:
                        if (wdata == 16'd1) ext_out <= !ext_out;
                        else if (wdata[1:0] == 2'd2) adc_select <= wdata[4:2];
                endcase
            end
        end
        wave_q <= wave[wave_addr];
    end

    for (genvar k = 0; k < NCH; k++) begin : g_env
        assign ch_env[k] = val[k];
        assign ch_env_next[k] = val_n[k];
    end
    assign fm_rem = rem;
endmodule
