// D130/D131 velocity/pressure keyboard (VPK), 160-button panel, 2 x 16
// display: sim/devices/synth.py VelocityKeyboard,
// docs/devices/d130-velocity-keyboard.md section 8.
//
//   CREG (D131) bits 0-1: mode (0 change register, 1 requests, 2 display,
//     3 lights); a rising bit 40 (EXW) without bit 20 hands DREG to the
//     keyboard: mode 1 latches the request, mode 2 writes display byte
//     DREG[7:0] at DREG[15:8], mode 3 light DREG[15:8] state DREG[1:0].
//   D130 read with CREG bit 100: CREG & 77 = 05 (KEYBOARD.CHECK) -> 0 (not
//     an ORK); mode 0 -> KCR (077777 with bit I clear while superoctave I
//     differs from the bits last answered); mode 1 -> the request's answer:
//       000|k velocity transit time, 200|k pressure, 200|88..95 analog
//       (89 with the switches in bits 8-15), 400|a superoctave a>>4's key
//       bits (marks them answered), 600 switch activity, 600|I bank I.
//   Other D130/D131 reads: no SYN when `strict`, else 0.
// Host ops (host_we): 0 key addr down, data = MIDI velocity (1-127);
//   1 key addr up; 2 button PBN addr, data[0] = down; 3 analog addr[2:0]
//   = data[7:0]; 4 switches = data[7:0]; 5 pressure of key addr = data[7:0].
//   Key addr = index 0-75 (NED key - 9, MIDI note - 33).
module dev_vpk (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic        reg_sel,      // 0 D130, 1 D131
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    output logic        nosyn,
    input  logic        strict,

    input  logic        host_we,
    input  logic [2:0]  host_op,
    input  logic [7:0]  host_addr,
    input  logic [7:0]  host_data,

    output logic [1:0]  lights [160], // by light address: 0 off, 1 on, 2 blink
    output logic [7:0]  chars [32],   // display: 0-15 upper line, 16-31 lower
    output logic [7:0]  dp [4]        // decimal-point words 32, 48, 36, 52 (p & 3 = 0..3)
);
    localparam logic [15:0] READ_BIT = 16'o100, STROBE_BIT = 16'o40;

    // MIDI velocity -> transit time (sim/devices/synth.py VELOCITY_TTIME)
    function automatic logic [7:0] ttime(input logic [6:0] v);
        case (v)
            // generated from sim/devices/synth.py VELOCITY_TTIME
            7'd0: ttime = 8'd124;
            7'd1: ttime = 8'd124;
            7'd2: ttime = 8'd115;
            7'd3: ttime = 8'd108;
            7'd4: ttime = 8'd98;
            7'd5: ttime = 8'd90;
            7'd6: ttime = 8'd85;
            7'd7: ttime = 8'd82;
            7'd8: ttime = 8'd78;
            7'd9: ttime = 8'd75;
            7'd10: ttime = 8'd72;
            7'd11: ttime = 8'd71;
            7'd12: ttime = 8'd68;
            7'd13: ttime = 8'd66;
            7'd14: ttime = 8'd64;
            7'd15: ttime = 8'd62;
            7'd16: ttime = 8'd61;
            7'd17: ttime = 8'd60;
            7'd18: ttime = 8'd58;
            7'd19: ttime = 8'd57;
            7'd20: ttime = 8'd56;
            7'd21: ttime = 8'd55;
            7'd22: ttime = 8'd54;
            7'd23: ttime = 8'd53;
            7'd24: ttime = 8'd52;
            7'd25: ttime = 8'd51;
            7'd26: ttime = 8'd50;
            7'd27: ttime = 8'd49;
            7'd28: ttime = 8'd49;
            7'd29: ttime = 8'd48;
            7'd30: ttime = 8'd47;
            7'd31: ttime = 8'd46;
            7'd32: ttime = 8'd46;
            7'd33: ttime = 8'd45;
            7'd34: ttime = 8'd45;
            7'd35: ttime = 8'd44;
            7'd36: ttime = 8'd43;
            7'd37: ttime = 8'd43;
            7'd38: ttime = 8'd42;
            7'd39: ttime = 8'd42;
            7'd40: ttime = 8'd41;
            7'd41: ttime = 8'd41;
            7'd42: ttime = 8'd40;
            7'd43: ttime = 8'd40;
            7'd44: ttime = 8'd39;
            7'd45: ttime = 8'd39;
            7'd46: ttime = 8'd39;
            7'd47: ttime = 8'd38;
            7'd48: ttime = 8'd38;
            7'd49: ttime = 8'd37;
            7'd50: ttime = 8'd37;
            7'd51: ttime = 8'd37;
            7'd52: ttime = 8'd36;
            7'd53: ttime = 8'd36;
            7'd54: ttime = 8'd35;
            7'd55: ttime = 8'd35;
            7'd56: ttime = 8'd35;
            7'd57: ttime = 8'd34;
            7'd58: ttime = 8'd34;
            7'd59: ttime = 8'd34;
            7'd60: ttime = 8'd33;
            7'd61: ttime = 8'd33;
            7'd62: ttime = 8'd33;
            7'd63: ttime = 8'd32;
            7'd64: ttime = 8'd32;
            7'd65: ttime = 8'd32;
            7'd66: ttime = 8'd32;
            7'd67: ttime = 8'd31;
            7'd68: ttime = 8'd31;
            7'd69: ttime = 8'd31;
            7'd70: ttime = 8'd30;
            7'd71: ttime = 8'd30;
            7'd72: ttime = 8'd30;
            7'd73: ttime = 8'd30;
            7'd74: ttime = 8'd29;
            7'd75: ttime = 8'd29;
            7'd76: ttime = 8'd29;
            7'd77: ttime = 8'd29;
            7'd78: ttime = 8'd29;
            7'd79: ttime = 8'd28;
            7'd80: ttime = 8'd28;
            7'd81: ttime = 8'd28;
            7'd82: ttime = 8'd28;
            7'd83: ttime = 8'd27;
            7'd84: ttime = 8'd27;
            7'd85: ttime = 8'd27;
            7'd86: ttime = 8'd27;
            7'd87: ttime = 8'd27;
            7'd88: ttime = 8'd26;
            7'd89: ttime = 8'd26;
            7'd90: ttime = 8'd26;
            7'd91: ttime = 8'd26;
            7'd92: ttime = 8'd26;
            7'd93: ttime = 8'd25;
            7'd94: ttime = 8'd25;
            7'd95: ttime = 8'd25;
            7'd96: ttime = 8'd25;
            7'd97: ttime = 8'd25;
            7'd98: ttime = 8'd24;
            7'd99: ttime = 8'd24;
            7'd100: ttime = 8'd24;
            7'd101: ttime = 8'd24;
            7'd102: ttime = 8'd24;
            7'd103: ttime = 8'd24;
            7'd104: ttime = 8'd23;
            7'd105: ttime = 8'd23;
            7'd106: ttime = 8'd23;
            7'd107: ttime = 8'd23;
            7'd108: ttime = 8'd23;
            7'd109: ttime = 8'd23;
            7'd110: ttime = 8'd22;
            7'd111: ttime = 8'd22;
            7'd112: ttime = 8'd22;
            7'd113: ttime = 8'd22;
            7'd114: ttime = 8'd22;
            7'd115: ttime = 8'd22;
            7'd116: ttime = 8'd22;
            7'd117: ttime = 8'd21;
            7'd118: ttime = 8'd21;
            7'd119: ttime = 8'd21;
            7'd120: ttime = 8'd21;
            7'd121: ttime = 8'd21;
            7'd122: ttime = 8'd21;
            7'd123: ttime = 8'd21;
            7'd124: ttime = 8'd20;
            7'd125: ttime = 8'd20;
            7'd126: ttime = 8'd20;
            7'd127: ttime = 8'd20;
            default: ttime = 8'd20;
        endcase
    endfunction

    logic [15:0] creg, dreg;
    logic [8:0]  request;
    logic [15:0] keys [5], reported [5];
    logic [7:0]  velocity [80], pressure [80];
    logic [7:0]  analog [8];
    logic [7:0]  switches;
    logic [15:0] banks [11];        // 1-10

    // --------------------------------------------------------------- reads
    logic [15:0] kcr, answer, sar;
    always_comb begin
        kcr = 16'o077777;
        for (int i = 0; i < 5; i++) if (keys[i] != reported[i]) kcr[i] = 1'b0;
        sar = '0;
        for (int i = 1; i <= 10; i++) if (banks[i] != 16'd0) sar[i - 1] = 1'b1;
        answer = '0;
        case (request[8:7])
            2'd0: if (request[6:0] < 7'd80) answer = {8'd0, velocity[request[6:0]]};
            2'd1: if (request[6:0] >= 7'd88)
                      answer = {request[6:0] == 7'd89 ? switches : 8'd0, analog[request[2:0]]};
                  else if (request[6:0] < 7'd80) answer = {8'd0, pressure[request[6:0]]};
            2'd2: if (request[6:4] < 3'd5) answer = keys[request[6:4]];
            2'd3: if (request[6:0] == 7'd0) answer = sar;
                  else if (request[6:0] <= 7'd10) answer = banks[request[3:0]];
        endcase
    end

    wire check = creg[5:0] == 6'o05;                       // KEYBOARD.CHECK: 105
    wire known = !reg_sel && (creg & READ_BIT) != 0;
    // the answer to the current request, a clock old: a read comes at least
    // three clocks after anything it depends on changes (timing: an 80-way
    // multiplexer)
    logic [15:0] answer_q;
    always_ff @(posedge clk) answer_q <= answer;
    assign rdata = !known || check ? 16'd0 :
                   creg[1:0] == 2'd0 ? kcr :
                   creg[1:0] == 2'd1 ? answer_q : 16'd0;
    assign nosyn = sel && rd && !known && strict;
    assign ack   = sel && !nosyn;

    // -------------------------------------------------------------- writes
    wire [6:0] hk = host_addr[6:0];
    wire [2:0] hso = 3'(hk >> 4);
    wire [3:0] hbit = hk[3:0];
    wire [3:0] hbank = 4'd10 - host_addr[7:4];

    always_ff @(posedge clk) begin
        if (rst) begin
            creg <= '0;
            dreg <= '0;
            request <= '0;
            switches <= '0;
            for (int i = 0; i < 5; i++) begin keys[i] <= '0; reported[i] <= '0; end
            for (int i = 0; i < 80; i++) begin velocity[i] <= '0; pressure[i] <= '0; end
            analog[0] <= 8'd128; analog[1] <= 8'd0;   analog[2] <= 8'd255; analog[3] <= 8'd255;
            analog[4] <= 8'd128; analog[5] <= 8'd0;   analog[6] <= 8'd0;   analog[7] <= 8'd255;
            for (int i = 0; i < 11; i++) banks[i] <= '0;
            for (int i = 0; i < 160; i++) lights[i] <= '0;
            for (int i = 0; i < 32; i++) chars[i] <= 8'o40;
            for (int i = 0; i < 4; i++) dp[i] <= '0;
        end else begin
            if (host_we) begin
                case (host_op)
                    3'd0: if (hk < 7'd76) begin
                        if (!keys[hso][hbit])
                            velocity[hk] <= ttime(host_data[6:0] == 7'd0 ? 7'd1 : host_data[6:0]);
                        keys[hso][hbit] <= 1'b1;
                    end
                    3'd1: if (hk < 7'd76) begin
                        keys[hso][hbit] <= 1'b0;
                        pressure[hk] <= '0;
                    end
                    3'd2: if (host_addr < 8'd160) banks[hbank][host_addr[3:0]] <= host_data[0];
                    3'd3: analog[host_addr[2:0]] <= host_data;
                    3'd4: switches <= host_data;
                    3'd5: if (hk < 7'd80) pressure[hk] <= host_data;
                    default: ;
                endcase
            end
            if (ack && rd && known && !check && creg[1:0] == 2'd1 && request[8:7] == 2'd2
                    && request[6:4] < 3'd5)
                reported[request[6:4]] <= keys[request[6:4]];
            if (ack && wr) begin
                if (reg_sel) begin
                    creg <= wdata;
                    if (wdata[5] && !creg[5] && !wdata[4]) begin
                        case (wdata[1:0])
                            2'd1: request <= dreg[8:0];
                            2'd2: if (dreg[15:8] < 8'd32) chars[dreg[12:8]] <= dreg[7:0];
                                  else case (dreg[15:8])
                                      8'd32: dp[0] <= dreg[7:0];
                                      8'd48: dp[1] <= dreg[7:0];
                                      8'd36: dp[2] <= dreg[7:0];
                                      8'd52: dp[3] <= dreg[7:0];
                                      default: ;
                                  endcase
                            2'd3: if (dreg[15:8] < 8'd160)
                                      lights[dreg[15:8]] <= dreg[1:0] == 2'd3 ? 2'd1 : dreg[1:0];
                            default: ;
                        endcase
                    end
                end else dreg <= wdata;
            end
        end
    end
endmodule
