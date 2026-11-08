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
// Running status is handled; real-time bytes (F8-FF) are ignored anywhere;
// system common and SysEx data are skipped.
//
// The clavier is negative logic (a 1 bit is a key up), 12 keys per word,
// 6 words (the last has only the top C); a changed word is written whole.
module midi_in #(
    parameter longint CLK_HZ = 50_000_000,
    parameter longint BAUD = 31_250
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        rxd,

    output logic        host_we,
    output logic        host_panel,
    output logic [2:0]  host_index,
    output logic [15:0] host_value,

    output logic        byte_valid,     // (for tests) a received byte
    output logic [7:0]  byte_data
);
    // ---------------------------------------------------------- UART receiver
    localparam int DIV = int'(CLK_HZ / BAUD);
    localparam int CW = $clog2(DIV + 1);
    logic [2:0]  sync;
    logic        busy;
    logic [CW-1:0] cnt;
    logic [3:0]  bitn;
    logic [7:0]  sh;
    always_ff @(posedge clk) begin
        sync <= {sync[1:0], rxd};
        byte_valid <= 1'b0;
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
                    byte_valid <= 1'b1;
                    byte_data <= sh;
                end
            end
            bitn <= bitn + 4'd1;
        end
    end

    // ------------------------------------------------------------- parser
    logic [7:0] status;                 // running status (0: none)
    logic       have1;                  // first data byte received
    logic [6:0] d1;
    // a complete message: kind 0 note off, 1 note on, 2 program, 3 control
    logic       msg;
    logic [1:0] kind;
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
                    4'h8, 4'h9, 4'hb: begin                    // two data bytes
                        if (!have1) begin
                            d1 <= byte_data[6:0];
                            have1 <= 1'b1;
                        end else begin
                            have1 <= 1'b0;
                            msg <= 1'b1;
                            chan <= status[3:0];
                            m1 <= d1;
                            m2 <= byte_data[6:0];
                            kind <= status[7:4] == 4'hb ? 2'd3 :
                                    (status[7:4] == 4'h9 && byte_data[6:0] != 7'd0) ? 2'd1 : 2'd0;
                        end
                    end
                    4'hc: begin                                // program change
                        msg <= 1'b1;
                        chan <= status[3:0];
                        m1 <= byte_data[6:0];
                        kind <= 2'd2;
                    end
                    4'ha, 4'he: begin                          // two bytes, ignored
                        have1 <= !have1;
                    end
                    default: ;                                 // D0: one byte, ignored
                endcase
            end
        end
    end

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
                    2'd0, 2'd1:
                        if (chan == 4'hf) begin                // panel button
                            panel[m1[6:4]][m1[3:0]] <= kind[0];
                            dirty_p[m1[6:4]] <= 1'b1;
                        end else begin                         // key: 0 = down
                            clav[oct][bit_] <= !kind[0];
                            dirty_c[oct] <= 1'b1;
                        end
                    2'd2: if (pst == P_IDLE) begin
                        prog <= m1;
                        pst <= P_BANK;
                        timer <= '0;
                        panel[6][{1'b0, m1[5:3]}] <= 1'b1;   // bank.n = PBN 96 + n
                        dirty_p[6] <= 1'b1;
                    end
                    default:
                        if (m1 == 7'd123 || m1 == 7'd120) begin
                            for (int i = 0; i < 5; i++) clav[i] <= 12'hfff;
                            clav[5] <= 12'h001;
                            dirty_c <= 6'h3f;
                        end
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
