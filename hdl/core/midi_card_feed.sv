// MIDI in to the MIDI subsystem card (dev_midi.sv) when the state image has
// the card (D51 bit 8): SYN-5.3 parses MIDI itself, so the card gets the
// bytes, rebuilt from midi_in.sv's decoded messages (status byte every
// time, no running status), plus the real-time bytes F8 clock, FA start,
// FB continue and FC stop (SYN-5.3's MIDI sync). SysEx, system common, FE
// active sensing and FF are not passed.
//
// Messages that are panel controls stay with the keyboard paths and are not
// passed (`panel`, combinational on msg_*):
//   channel 16 notes: panel buttons (midi_in.sv, midi_vpk.sv);
//   with the velocity keyboard (vpk): channel 15 notes (PBN 128-159),
//   channel 10 notes 36-51 (Launchkey pads), CC 21-28 (Launchkey pots).
// Program change is passed and also recalls a timbre through the panel.
//
// One byte a clock leaves on out_valid/out_data. A message arriving while
// the previous one is still leaving (3 clocks) is dropped; at MIDI speed
// bytes are at least 320 us apart, so this does not happen.
module midi_card_feed (
    input  logic       clk,
    input  logic       rst,
    input  logic       vpk,

    input  logic       msg_valid,      // midi_in.sv msg_*
    input  logic [2:0] msg_kind,
    input  logic [3:0] msg_chan,
    input  logic [6:0] msg_m1,
    input  logic [6:0] msg_m2,
    input  logic       byte_valid,     // midi_in.sv byte_valid/byte_data (raw)
    input  logic [7:0] byte_data,

    output logic       panel,
    output logic       out_valid,
    output logic [7:0] out_data
);
    wire note = msg_kind == 3'd0 || msg_kind == 3'd1;
    always_comb begin
        panel = note && msg_chan == 4'd15;
        if (vpk && ((note && msg_chan == 4'd14) ||
                    (note && msg_chan == 4'd9 && msg_m1 >= 7'd36 && msg_m1 <= 7'd51) ||
                    (msg_kind == 3'd3 && msg_m1 >= 7'd21 && msg_m1 <= 7'd28)))
            panel = 1'b1;
    end

    logic [3:0] hi;
    always_comb
        case (msg_kind)
            3'd0: hi = 4'h8;
            3'd1: hi = 4'h9;
            3'd2: hi = 4'hc;
            3'd3: hi = 4'hb;
            3'd4: hi = 4'he;
            3'd5: hi = 4'ha;
            default: hi = 4'hd;
        endcase

    wire rt = byte_valid && (byte_data == 8'hf8 || byte_data == 8'hfa ||
                             byte_data == 8'hfb || byte_data == 8'hfc);
    logic [7:0] b1, b2;
    logic [1:0] n;                     // bytes still to send after out_data
    always_ff @(posedge clk) begin
        if (rst) begin
            out_valid <= 1'b0; n <= '0;
        end else if (out_valid && n != 2'd0) begin
            out_data <= b1; b1 <= b2; n <= n - 2'd1;
        end else if (msg_valid && !panel) begin
            out_valid <= 1'b1;
            out_data <= {hi, msg_chan};
            b1 <= {1'b0, msg_m1};
            b2 <= {1'b0, msg_m2};
            n <= (msg_kind == 3'd2 || msg_kind == 3'd6) ? 2'd1 : 2'd2;
        end else if (rt) begin
            out_valid <= 1'b1; out_data <= byte_data; n <= '0;
        end else
            out_valid <= 1'b0;
    end
endmodule
