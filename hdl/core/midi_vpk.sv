// MIDI messages (midi_in.sv msg_*) to the velocity/pressure keyboard
// (dev_vpk.sv host ops). Defaults suit a Novation Launchkey MK3:
//
//   notes, channels 1-9 and 11-14: VPK keys with velocity; MIDI 33-108
//     (folded by octaves into range), middle C = MIDI 60 = NED key 36.
//   channel 10 notes 36-51 (Launchkey drum pads): panel buttons, PAD table
//     below; other channel 10 notes: keys.
//   channel 16 note n: panel button PBN n (0-127); channel 15 note n:
//     PBN 128 + n (0-31). Note on presses, note off releases.
//   pitch bend: pitch wheel (centre 128, +/-96); CC 1 mod wheel; CC 2
//     breath; CC 4 pedal 1; CC 11 pedal 2; CC 16 ribbon; CC 64 sustain
//     switch; key pressure: that key's pressure; channel pressure: every
//     held key's pressure.
//   CC 21 (pot 1): the control knob, relative: each step of the pot is one
//     step of the selected parameter (a fast turn, 3+ per message, counts 4
//     each). SYN-5.3 reads the knob as a deflection from rest (395-UPDT), so
//     steps are sent as short deflections: +-40 (1 step), +-61 (3), +-66 (8),
//     held 20 ms, then rest 30 ms.
//   CC 22-28 (pots 2-8): the same, after pressing the pot's parameter button
//     (POT table) if another parameter was last selected by a pot.
//   program change p: BANK, button timb.(p/8 mod 8), ENTRY, timb.(p mod 8):
//     bank (p/8)+1, entry (p mod 8)+1; buttons held 100 ms, 200 ms apart,
//     1.5 s after the bank number (the bank is read from disk).
//   CC 120/123: all keys up.
module midi_vpk #(
    parameter longint CLK_HZ = 50_000_000
) (
    input  logic       clk,
    input  logic       rst,
    input  logic       msg_valid,
    input  logic [2:0] msg_kind,
    input  logic [3:0] msg_chan,
    input  logic [6:0] msg_m1,
    input  logic [6:0] msg_m2,

    output logic       host_we,
    output logic [2:0] host_op,
    output logic [7:0] host_addr,
    output logic [7:0] host_data
);
    localparam logic [2:0] OP_DOWN = 3'd0, OP_UP = 3'd1, OP_BUTTON = 3'd2, OP_ANALOG = 3'd3,
                           OP_SWITCH = 3'd4, OP_PRESSURE = 3'd5;
    localparam logic [7:0] PBN_BANK = 8'd97, PBN_ENTRY = 8'd98, PBN_TIMB = 8'd104;

    // Launchkey MK3 drum pads (channel 10 notes 36-51) -> PBN
    function automatic logic [7:0] pad(input logic [3:0] n);
        case (n)
            4'd0:  pad = PBN_BANK;  // 36 bottom row: BANK ENTRY START STOP
            4'd1:  pad = PBN_ENTRY; // 37
            4'd2:  pad = 8'd32;     // 38 start
            4'd3:  pad = 8'd33;     // 39 stop
            4'd4:  pad = 8'd104;    // 40 top row: timb.0-3 (buttons 1-4)
            4'd5:  pad = 8'd105;
            4'd6:  pad = 8'd106;
            4'd7:  pad = 8'd107;
            4'd8:  pad = 8'd34;     // 44 bottom row: RECORD CONT REW FF
            4'd9:  pad = 8'd36;
            4'd10: pad = 8'd37;
            4'd11: pad = 8'd38;
            4'd12: pad = 8'd108;    // 48 top row: timb.4-7 (buttons 5-8)
            4'd13: pad = 8'd109;
            4'd14: pad = 8'd110;
            default: pad = 8'd111;
        endcase
    endfunction

    // pots 2-8 (CC 22-28) -> parameter button
    function automatic logic [7:0] pot_button(input logic [2:0] p);
        case (p)
            3'd1: pot_button = 8'd17;  // pvol    partial volume
            3'd2: pot_button = 8'd16;  // ptun    partial tuning
            3'd3: pot_button = 8'd24;  // ratio   FM ratio
            3'd4: pot_button = 8'd3;   // ve.atk  volume envelope attack
            3'd5: pot_button = 8'd4;   // ve.idec initial decay
            3'd6: pot_button = 8'd7;   // ve.sust sustain
            default: pot_button = 8'd5; // ve.fdec final decay
        endcase
    endfunction

    // note folding and controller scaling: tables (tools/gen_midi_tables.py)
    `include "midi_tables.svh"

    // ------------------------------------------------ immediate host ops
    logic       im_we;
    logic [2:0] im_op;
    logic [7:0] im_addr, im_data;
    logic [75:0] down;                  // keys held
    logic [7:0]  switches;
    logic [6:0]  sweep;                 // 0-75: pressure / release sweep position
    logic        sweeping, sweep_rel;
    logic [7:0]  sweep_val;

    // knob and button sequencer requests
    logic [7:0]  pot_last [8];
    logic [7:0]  pot_seen;
    logic [2:0]  pot_sel;               // pot whose button was pressed last (0: none)
    logic signed [11:0] pending;        // knob steps to send
    logic        tap_req;               // a button press to send before more knob steps
    logic [7:0]  tap_pbn;
    logic [2:0]  prog_stage;            // program change: taps left (4..1)
    logic [6:0]  prog;
    logic        seq_took_tap, seq_idle;     // from the sequencer below

    wire [6:0]  key = vpk_key(msg_m1);
    wire [10:0] bend = {msg_m2, msg_m1[6:3]};       // top 11 bits of 14
    wire signed [19:0] bdev = $signed({9'd0, bend}) - 20'sd1024;
    wire signed [19:0] braw = 20'sd128 + ((bdev * 20'sd96) >>> 10);
    wire [2:0]  pot = 3'(msg_m1 - 7'd21);
    wire signed [8:0] pdelta = $signed({2'b0, msg_m2}) - $signed({1'b0, pot_last[pot]});
    wire signed [11:0] pstep = (pdelta >= 9'sd3 || pdelta <= -9'sd3) ? 12'(pdelta) * 12'sd4
                                                                     : 12'(pdelta);

    // knob steps left after the ones the sequencer has just sent
    logic        seq_step_down;
    logic [1:0]  seq_step;
    logic [3:0]  seq_step_n;
    wire signed [11:0] pending_now = seq_step == 2'd0 ? pending :
                                     seq_step_down ? pending + 12'(seq_step_n)
                                                   : pending - 12'(seq_step_n);


    always_ff @(posedge clk) begin
        im_we <= 1'b0;
        if (rst) begin
            down <= '0;
            switches <= '0;
            sweeping <= 1'b0;
            pot_seen <= '0;
            pot_sel <= '0;
            pending <= '0;
            tap_req <= 1'b0;
            prog_stage <= '0;
        end else begin
            if (seq_took_tap) tap_req <= 1'b0;
            pending <= pending_now;
            if (seq_took_tap && prog_stage != 3'd0) prog_stage <= prog_stage - 3'd1;
            if (prog_stage != 3'd0 && !tap_req && !seq_took_tap && seq_idle) begin
                tap_req <= 1'b1;
                case (prog_stage)
                    3'd4: tap_pbn <= PBN_BANK;
                    3'd3: tap_pbn <= PBN_TIMB + {5'd0, prog[5:3]};
                    3'd2: tap_pbn <= PBN_ENTRY;
                    default: tap_pbn <= PBN_TIMB + {5'd0, prog[2:0]};
                endcase
            end
            if (sweeping) begin
                if (down[sweep]) begin
                    im_we <= 1'b1;
                    im_op <= sweep_rel ? OP_UP : OP_PRESSURE;
                    im_addr <= {1'b0, sweep};
                    im_data <= sweep_rel ? 8'd0 : sweep_val;
                    if (sweep_rel) down[sweep] <= 1'b0;
                end
                if (sweep == 7'd75) sweeping <= 1'b0;
                sweep <= sweep + 7'd1;
            end else if (msg_valid) begin
                case (msg_kind)
                    3'd0, 3'd1: begin
                        im_we <= 1'b1;
                        if (msg_chan == 4'd15 || (msg_chan == 4'd14 && msg_m1 < 7'd32)) begin
                            im_op <= OP_BUTTON;
                            im_addr <= msg_chan == 4'd15 ? {1'b0, msg_m1} : 8'd128 + {1'b0, msg_m1};
                            im_data <= {7'd0, msg_kind[0]};
                            pot_sel <= '0;              // a parameter may have been selected
                        end else if (msg_chan == 4'd9 && msg_m1 >= 7'd36 && msg_m1 <= 7'd51) begin
                            im_op <= OP_BUTTON;
                            im_addr <= pad(4'(msg_m1 - 7'd36));
                            im_data <= {7'd0, msg_kind[0]};
                            pot_sel <= '0;
                        end else begin
                            im_op <= msg_kind[0] ? OP_DOWN : OP_UP;
                            im_addr <= {1'b0, key};
                            im_data <= {1'b0, msg_m2};
                            down[key] <= msg_kind[0];
                        end
                    end
                    3'd2: if (prog_stage == 3'd0) begin
                        prog <= msg_m1;
                        prog_stage <= 3'd4;
                    end
                    3'd3: case (msg_m1)
                        7'd1:  begin im_we <= 1'b1; im_op <= OP_ANALOG; im_addr <= 8'd5;
                                     im_data <= 8'd13 + scale180(msg_m2); end
                        7'd2:  begin im_we <= 1'b1; im_op <= OP_ANALOG; im_addr <= 8'd6;
                                     im_data <= 8'd20 + scale225(msg_m2); end
                        7'd4:  begin im_we <= 1'b1; im_op <= OP_ANALOG; im_addr <= 8'd3;
                                     im_data <= 8'd235 - scale225(msg_m2); end
                        7'd11: begin im_we <= 1'b1; im_op <= OP_ANALOG; im_addr <= 8'd2;
                                     im_data <= 8'd235 - scale225(msg_m2); end
                        7'd16: begin im_we <= 1'b1; im_op <= OP_ANALOG; im_addr <= 8'd1;
                                     im_data <= msg_m2 == 7'd0 ? 8'd0 : 8'd28 + {1'b0, msg_m2}; end
                        7'd64: begin
                            im_we <= 1'b1; im_op <= OP_SWITCH; im_addr <= 8'd0;
                            im_data <= {switches[7:4], msg_m2[6], switches[2:0]};
                            switches[3] <= msg_m2[6];
                        end
                        7'd120, 7'd123: begin
                            sweeping <= 1'b1; sweep <= '0; sweep_rel <= 1'b1;
                        end
                        default:
                            if (msg_m1 >= 7'd21 && msg_m1 <= 7'd28) begin
                                pot_last[pot] <= {1'b0, msg_m2};
                                pot_seen[pot] <= 1'b1;
                                if (pot_seen[pot] && pdelta != 9'sd0) begin
                                    if (pot != 3'd0 && pot != pot_sel) begin
                                        pot_sel <= pot;
                                        tap_req <= 1'b1;            // select its parameter first
                                        tap_pbn <= pot_button(pot);
                                        pending <= pstep;           // steps for another one are dropped
                                    end else pending <= pending_now + pstep;
                                end
                            end
                    endcase
                    3'd4: begin
                        im_we <= 1'b1; im_op <= OP_ANALOG; im_addr <= 8'd4;
                        im_data <= braw < 0 ? 8'd0 : braw > 255 ? 8'd255 : 8'(braw);
                    end
                    3'd5: begin
                        im_we <= 1'b1; im_op <= OP_PRESSURE; im_addr <= {1'b0, key};
                        im_data <= {msg_m2, 1'b0};
                    end
                    3'd6: begin
                        sweeping <= 1'b1; sweep <= '0; sweep_rel <= 1'b0;
                        sweep_val <= {msg_m1, 1'b0};
                    end
                    default: ;
                endcase
            end
        end
    end

    // ------------------------------------------- button taps, knob pulses
    localparam longint MS = CLK_HZ / 1000;
    localparam int TW = $clog2(1500 * MS + 1);
    localparam logic [2:0] Q_IDLE = 3'd0, Q_TAP = 3'd1, Q_TAP_GAP = 3'd2, Q_KNOB = 3'd3,
                           Q_KNOB_GAP = 3'd4;
    logic [2:0]  q;
    logic [TW-1:0] t, gap;
    logic        q_we;
    logic [2:0]  q_op;
    logic [7:0]  q_addr, q_data;
    logic [7:0]  cur_pbn;
    assign seq_idle = q == Q_IDLE;

    always_ff @(posedge clk) begin
        seq_took_tap <= 1'b0;
        seq_step <= 2'd0;
        if (rst) begin
            q <= Q_IDLE;
            q_we <= 1'b0;
        end else begin
            if (q_we && !im_we) q_we <= 1'b0;          // sent (an immediate op goes first)
            case (q)
                Q_IDLE:
                    if (!q_we) begin
                        if (tap_req && !seq_took_tap) begin
                            seq_took_tap <= 1'b1;
                            cur_pbn <= tap_pbn;
                            q_we <= 1'b1; q_op <= OP_BUTTON; q_addr <= tap_pbn; q_data <= 8'd1;
                            gap <= TW'((prog_stage == 3'd3 ? 1500 : 200) * MS);
                            t <= '0;
                            q <= Q_TAP;
                        end else if (pending != 12'sd0 && !tap_req) begin
                            q_we <= 1'b1; q_op <= OP_ANALOG; q_addr <= 8'd0;
                            seq_step <= 2'd1;
                            seq_step_down <= pending < 0;
                            if (pending >= 12'sd8 || pending <= -12'sd8) begin
                                q_data <= pending < 0 ? 8'd62 : 8'd194;   // 128 -+ 66: 8 steps
                                seq_step_n <= 4'd8;
                            end else if (pending >= 12'sd3 || pending <= -12'sd3) begin
                                q_data <= pending < 0 ? 8'd67 : 8'd189;   // 128 -+ 61: 3 steps
                                seq_step_n <= 4'd3;
                            end else begin
                                q_data <= pending < 0 ? 8'd88 : 8'd168;   // 128 -+ 40: 1 step
                                seq_step_n <= 4'd1;
                            end
                            t <= '0;
                            q <= Q_KNOB;
                        end
                    end
                Q_TAP: if (!q_we) begin
                    if (t == TW'(100 * MS)) begin
                        q_we <= 1'b1; q_op <= OP_BUTTON; q_addr <= cur_pbn; q_data <= 8'd0;
                        t <= '0;
                        q <= Q_TAP_GAP;
                    end else t <= t + 1'b1;
                end
                Q_TAP_GAP: if (!q_we) begin
                    if (t == gap) q <= Q_IDLE;
                    else t <= t + 1'b1;
                end
                Q_KNOB: if (!q_we) begin
                    if (t == TW'(20 * MS)) begin
                        q_we <= 1'b1; q_op <= OP_ANALOG; q_addr <= 8'd0; q_data <= 8'd128;
                        t <= '0;
                        q <= Q_KNOB_GAP;
                    end else t <= t + 1'b1;
                end
                Q_KNOB_GAP: if (!q_we) begin
                    if (t == TW'(30 * MS)) q <= Q_IDLE;
                    else t <= t + 1'b1;
                end
                default: q <= Q_IDLE;
            endcase
        end
    end

    // one op a clock: an immediate one first, the sequencer's waits a clock
    assign host_we   = im_we || q_we;
    assign host_op   = im_we ? im_op : q_op;
    assign host_addr = im_we ? im_addr : q_addr;
    assign host_data = im_we ? im_data : q_data;
endmodule
