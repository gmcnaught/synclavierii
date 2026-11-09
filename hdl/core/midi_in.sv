// MIDI input (31250 baud, from MiSTer's UART: MidiLink forwards USB MIDI)
// to the original keyboard and button panel (dev_keyboard host port).
//
//   channels 1-15, note on/off: clavier keys. MIDI note 36 (C2 on most
//     61-key controllers) is the ORK's lowest key (Python key 12, "C1"),
//     MIDI 96 its highest; notes outside are moved by octaves into range.
//   channel 16, note on/off: panel button with physical button number =
//     note (0-127; sim/devices/synth.py ORK_BUTTONS, NED 05-BUTT:075-OLDL).
//   program change p (any channel): recall timbre p as on the panel:
//     bank.(p/8) for 100 ms, then 1.5 s later timb.(p%8) for 100 ms (the
//     timing of the ORK-LM note test, sim/lockstep.py ork_lm_note_actions).
//   control 123 (all notes off) or 120: all keys up.
// The decoded messages are also outputs (msg_*), for midi_vpk.sv: kind 0
// note off, 1 note on, 2 program change, 3 control change, 4 pitch bend
// (m1 = LSB, m2 = MSB), 5 polyphonic key pressure, 6 channel pressure.
// Running status is handled; real-time bytes (F8-FF) are ignored anywhere;
// system common and SysEx data are skipped.
//
// The clavier is negative logic (a 1 bit is a key up), 12 keys per word,
// 6 words (the last has only the top C); a changed word is written whole.
//
// Line speed: MIDI is 31250 baud, but on a MiSTer whose ttyS1 loses its
// speed setting (MidiLink's own source says so; observed on a 6.18 kernel:
// the line falls back to 9600 after MidiLink sets 31250) the bytes arrive
// at ALT_BAUD. Both are received; the 31250 receiver is used until it sees
// framing errors while the ALT_BAUD one decodes cleanly (a 9600 line gives
// the 31250 receiver an error for nearly every byte). It goes back to 31250
// the same way, or when 7 bytes in a row decode cleanly at 31250 (a 31250
// line can look clean to the 9600 receiver; a 9600 line never gives the
// 31250 receiver such a run). `alt` says which is in use.
module midi_in #(
    parameter longint CLK_HZ = 50_000_000,
    parameter longint BAUD = 31_250,
    parameter longint ALT_BAUD = 9_600
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        rxd,

    output logic        host_we,
    output logic        host_panel,
    output logic [2:0]  host_index,
    output logic [15:0] host_value,

    output logic        byte_valid,     // a received byte (tests, the status line)
    output logic [7:0]  byte_data,
    output logic        frame_err,      // a byte whose stop bit was low (dropped)
    output logic        alt,            // receiving at ALT_BAUD

    output logic        msg_valid,      // a decoded channel message
    output logic [2:0]  msg_kind,
    output logic [3:0]  msg_chan,
    output logic [6:0]  msg_m1,
    output logic [6:0]  msg_m2
);
    // ---------------------------------------------------------- UART receivers
    logic       v_std, e_std, v_alt, e_alt;
    logic [7:0] d_std, d_alt;
    midi_uart_rx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) rx_std (
        .clk, .rst, .rxd, .valid(v_std), .data(d_std), .ferr(e_std));
    midi_uart_rx #(.CLK_HZ(CLK_HZ), .BAUD(ALT_BAUD)) rx_alt (
        .clk, .rst, .rxd, .valid(v_alt), .data(d_alt), .ferr(e_alt));

    // speed choice: errors on the receiver in use (since its last good byte)
    // and clean bytes in a row on the other
    logic [2:0] bad_cur, good_other;
    wire        v_cur = alt ? v_alt : v_std, e_cur = alt ? e_alt : e_std;
    wire        v_oth = alt ? v_std : v_alt, e_oth = alt ? e_std : e_alt;
    always_ff @(posedge clk) begin
        if (rst) begin
            alt <= 1'b0;
            bad_cur <= '0;
            good_other <= '0;
        end else if ((bad_cur >= 3'd3 && good_other >= 3'd4) || (alt && good_other == 3'd7)) begin
            alt <= !alt;                          // the other speed decodes cleanly
            bad_cur <= '0;
            good_other <= '0;
        end else begin
            if (e_cur && bad_cur != 3'd7) bad_cur <= bad_cur + 3'd1;
            else if (v_cur) bad_cur <= '0;
            if (e_oth) good_other <= '0;
            else if (v_oth && good_other != 3'd7) good_other <= good_other + 3'd1;
        end
    end
    assign byte_valid = v_cur;
    assign byte_data  = alt ? d_alt : d_std;
    assign frame_err  = e_cur;

    // ------------------------------------------------------------- parser
    logic [7:0] status;                 // running status (0: none)
    logic       have1;                  // first data byte received
    logic [6:0] d1;
    // a complete message: kind 0 note off, 1 note on, 2 program, 3 control,
    // 4 pitch bend, 5 key pressure, 6 channel pressure
    logic       msg;
    logic [2:0] kind;
    logic [3:0] chan;
    logic [6:0] m1, m2;

    always_ff @(posedge clk) begin
        msg <= 1'b0;
        if (rst) begin
            status <= 8'd0;
            have1 <= 1'b0;
        end else if (byte_valid) begin
            if (byte_data >= 8'hf8) begin
                ;                                     // real time: no effect
            end else if (byte_data[7]) begin
                status <= byte_data < 8'hf0 ? byte_data : 8'd0;   // system: drop status
                have1 <= 1'b0;
            end else if (status != 8'd0) begin
                case (status[7:4])
                    4'h8, 4'h9, 4'ha, 4'hb, 4'he: begin        // two data bytes
                        if (!have1) begin
                            d1 <= byte_data[6:0];
                            have1 <= 1'b1;
                        end else begin
                            have1 <= 1'b0;
                            msg <= 1'b1;
                            chan <= status[3:0];
                            m1 <= d1;
                            m2 <= byte_data[6:0];
                            kind <= status[7:4] == 4'hb ? 3'd3 :
                                    status[7:4] == 4'he ? 3'd4 :
                                    status[7:4] == 4'ha ? 3'd5 :
                                    (status[7:4] == 4'h9 && byte_data[6:0] != 7'd0) ? 3'd1 : 3'd0;
                        end
                    end
                    4'hc, 4'hd: begin                          // program change, channel pressure
                        msg <= 1'b1;
                        chan <= status[3:0];
                        m1 <= byte_data[6:0];
                        m2 <= 7'd0;
                        kind <= status[7:4] == 4'hc ? 3'd2 : 3'd6;
                    end
                    default: ;
                endcase
            end
        end
    end

    assign msg_valid = msg;
    assign msg_kind  = kind;
    assign msg_chan  = chan;
    assign msg_m1    = m1;
    assign msg_m2    = m2;

    // --------------------------------------------------- keyboard and panel
    logic [11:0] clav [6];
    logic [15:0] panel [8];

    // note -> clavier octave and bit: fold into MIDI 36..96
    logic [6:0] n;
    always_comb begin
        n = m1;
        if (n < 7'd36) n = n + 7'd12 * 7'(((7'd47 - n) / 7'd12));
        if (n > 7'd96) n = n - 7'd12 * 7'(((n - 7'd85) / 7'd12));
    end
    wire [6:0] k = n - 7'd36;                 // 0..60
    wire [2:0] oct = 3'(k / 7'd12);
    wire [3:0] bit_ = 4'(k % 7'd12);

    // program change sequencer (real time)
    localparam longint MS = CLK_HZ / 1000;
    localparam int TW = $clog2(1700 * MS + 1);
    typedef enum logic [2:0] {P_IDLE, P_BANK, P_GAP, P_TIMB, P_DONE} pstate_t;
    pstate_t pst;
    logic [TW-1:0] timer;
    logic [6:0]  prog;

    // one write per clock: pending clavier octave or panel word
    logic [5:0] dirty_c;
    logic [7:0] dirty_p;

    always_ff @(posedge clk) begin
        host_we <= 1'b0;
        if (rst) begin
            for (int i = 0; i < 5; i++) clav[i] <= 12'hfff;
            clav[5] <= 12'h001;
            for (int i = 0; i < 8; i++) panel[i] <= 16'h0000;
            dirty_c <= '0;
            dirty_p <= '0;
            pst <= P_IDLE;
        end else begin
            if (msg) begin
                case (kind)
                    3'd0, 3'd1:
                        if (chan == 4'hf) begin                // panel button
                            panel[m1[6:4]][m1[3:0]] <= kind[0];
                            dirty_p[m1[6:4]] <= 1'b1;
                        end else begin                         // key: 0 = down
                            clav[oct][bit_] <= !kind[0];
                            dirty_c[oct] <= 1'b1;
                        end
                    3'd2: if (pst == P_IDLE) begin
                        prog <= m1;
                        pst <= P_BANK;
                        timer <= '0;
                        panel[6][{1'b0, m1[5:3]}] <= 1'b1;   // bank.n = PBN 96 + n
                        dirty_p[6] <= 1'b1;
                    end
                    3'd3:
                        if (m1 == 7'd123 || m1 == 7'd120) begin
                            for (int i = 0; i < 5; i++) clav[i] <= 12'hfff;
                            clav[5] <= 12'h001;
                            dirty_c <= 6'h3f;
                        end
                    default: ;
                endcase
            end else if (dirty_c == '0 && dirty_p == '0) begin
                // (the sequencer waits while words are being written out)
                case (pst)
                    P_BANK: if (timer == TW'(100 * MS)) begin
                        panel[6][{1'b0, prog[5:3]}] <= 1'b0;
                        dirty_p[6] <= 1'b1;
                        pst <= P_GAP;
                    end else timer <= timer + 1'b1;
                    P_GAP: if (timer == TW'(1600 * MS)) begin
                        panel[6][{1'b1, prog[2:0]}] <= 1'b1;  // timb.n = PBN 104 + n
                        dirty_p[6] <= 1'b1;
                        pst <= P_TIMB;
                    end else timer <= timer + 1'b1;
                    P_TIMB: if (timer == TW'(1700 * MS)) begin
                        panel[6][{1'b1, prog[2:0]}] <= 1'b0;
                        dirty_p[6] <= 1'b1;
                        pst <= P_IDLE;
                    end else timer <= timer + 1'b1;
                    default: pst <= P_IDLE;
                endcase
            end

            // write out one changed word per clock (after the update above lands)
            if (!msg && dirty_c != '0) begin
                for (int i = 5; i >= 0; i--)
                    if (dirty_c[i]) begin
                        host_index <= 3'(i);
                        host_value <= {4'd0, clav[i]};
                        host_panel <= 1'b0;
                    end
                host_we <= 1'b1;
                dirty_c <= dirty_c & (dirty_c - 6'd1);   // lowest set bit done
            end else if (!msg && dirty_p != '0) begin
                for (int i = 7; i >= 0; i--)
                    if (dirty_p[i]) begin
                        host_index <= 3'(i);
                        host_value <= panel[i];
                        host_panel <= 1'b1;
                    end
                host_we <= 1'b1;
                dirty_p <= dirty_p & (dirty_p - 8'd1);
            end
        end
    end
endmodule

// One UART receiver (8N1) at CLK_HZ / BAUD clocks a bit: `valid` with the
// byte when the stop bit is high, `ferr` when it is low (byte dropped).
module midi_uart_rx #(
    parameter longint CLK_HZ = 50_000_000,
    parameter longint BAUD = 31_250
) (
    input  logic       clk,
    input  logic       rst,
    input  logic       rxd,
    output logic       valid,
    output logic [7:0] data,
    output logic       ferr
);
    localparam int DIV = int'(CLK_HZ / BAUD);
    localparam int CW = $clog2(DIV + 1);
    logic [2:0]  sync;
    logic        busy;
    logic [CW-1:0] cnt;
    logic [3:0]  bitn;
    logic [7:0]  sh;
    always_ff @(posedge clk) begin
        sync <= {sync[1:0], rxd};
        valid <= 1'b0;
        ferr <= 1'b0;
        if (rst) begin
            busy <= 1'b0;
            sync <= 3'b111;
        end else if (!busy) begin
            if (sync[2:1] == 2'b10) begin           // start bit edge
                busy <= 1'b1;
                cnt <= CW'(DIV / 2);
                bitn <= 4'd0;
            end
        end else if (cnt != '0) begin
            cnt <= cnt - 1'b1;
        end else begin
            cnt <= CW'(DIV - 1);
            if (bitn == 4'd0) begin
                if (sync[2]) busy <= 1'b0;          // not a start bit after all
            end else if (bitn <= 4'd8) begin
                sh <= {sync[2], sh[7:1]};
            end else begin
                busy <= 1'b0;
                if (sync[2]) begin                  // stop bit: the byte is good
                    valid <= 1'b1;
                    data <= sh;
                end else ferr <= 1'b1;
            end
            bitn <= bitn + 4'd1;
        end
    end
endmodule
