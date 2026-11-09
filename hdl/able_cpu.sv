// ABLE Model B CPU (M4.2). Behavioural, multi-cycle; one instruction is
// FETCH -> DECODE -> [SRC] -> EXEC -> TICK -> END.
//
// Semantics follow sim/cpu.py exactly (docs/instruction-set.md, choices in
// docs/simulator.md "Behaviour choices"); the two are checked against each
// other instruction by instruction (hdl/sim/lockstep.cpp, M4.3).
//
// Memory: 64K words, synchronous read (data one cycle after the address),
// synchronous write. I/O bus (devices 000-177 except 001): io_rd/io_wr and
// io_dev are held until the device answers with io_ack (SYN) or io_nosyn
// (no device: the CPU halts, as the real machine hangs). Device 001
// (PSW/PCW) is inside the CPU; `irq` is the device interrupt request bits
// 15-4 of the PSW.
//
// Time (as sim/cpu.py, for device models): each instruction costs 333 ns
// per bus transfer (fetch, source unless immediate, destination unless a
// transfer not taken). In TICK the CPU strobes `tick` with that time, so
// devices advance before END samples `irq`, as Python ticks the bus before
// its interrupt check. A read the device holds with `io_hold` (Python's
// BUS_WAIT, e.g. D50 with no character) costs 333 ns per clock held.
//
// `model` (1 B, 2 C, 3 D; sim/cpu.py `model`) selects the Model C and D
// extensions (docs/instruction-set.md section 9, docs/release-5.3.md):
//   C: ADC/SBB (270-277; no-ops on Model B, CHOICE); device 010 (D10):
//      write = repeat count (the next instruction runs (n mod 256) + 1
//      times, without new fetches, uninterrupted), read = the link (PC
//      after the last taken absolute transfer, or the interrupted PC);
//      device 002 (D2) priority encoder (read = 2 x highest bit written);
//      destination 372 stores at R12, then decrements R12; no interrupt
//      right after a PCW write or a taken absolute transfer.
//   D: device 011 (D11) instruction page (bits 15-8 only): while R17 is the
//      PC, fetches and reads through R17 come from external memory word
//      {page, address} (code port cm_*; page 0 = internal memory); device
//      057 (D57) reads `d57`.
// Devices 002/010 (C, D) and 011/057 (D) are inside the CPU; on Model B they
// go out on the I/O bus as before.

module able_cpu (
    input  logic        clk,
    input  logic        rst,          // INIT
    input  logic [1:0]  model,        // 1 B, 2 C, 3 D
    input  logic [15:0] d57,          // Model D: D57 options bits

    output logic [23:0] cm_addr,      // Model D code fetch from external memory
    output logic        cm_rd,
    input  logic [15:0] cm_rdata,
    input  logic        cm_ack,

    output logic [15:0] mem_addr,
    output logic        mem_we,
    output logic [15:0] mem_wdata,
    input  logic [15:0] mem_rdata,

    output logic        io_rd,
    output logic        io_wr,
    output logic [6:0]  io_dev,
    output logic [15:0] io_wdata,
    input  logic [15:0] io_rdata,
    input  logic        io_ack,
    input  logic        io_nosyn,
    input  logic        io_hold,      // read not ready yet: hold, 333 ns per clock

    output logic        io_held,      // this clock is a held read (ticks 333 ns)
    output logic        tick,         // devices: advance time by tick_ns
    output logic [9:0]  tick_ns,

    input  logic [15:4] irq,
    output logic        irq_sample,   // irq is sampled at this clock edge
    output logic        irq_psw,      // ... for a PSW read (else end of instruction)

    input  logic        stall,        // real-time throttle: wait before the next fetch
    input  logic        halt_req,
    output logic        halted,
    output logic [1:0]  halt_reason,  // 1 no SYN on read, 2 no SYN on write, 3 HALT

    output logic        instr_done,   // END state: instruction at instr_pc completes
    output logic [15:0] instr_pc,
    output logic [15:0] instr_word,

    // debug: register/flag load while in reset, and state outputs
    input  logic        dbg_we,
    input  logic [4:0]  dbg_addr,     // 0-15 registers, 16 = {pcs, ion, m, c, z},
                                      // 17 page, 18 ppc, 19 {rpt_next, rpt_left},
                                      // 20 repeat word, 21 repeat pc, 22 D2,
                                      // 23 interrupt shadow
    input  logic [15:0] dbg_wdata,
    output logic [255:0] regs_flat,
    output logic [4:0]  flags         // {pcs, ion, m, c, z}
);

    typedef enum logic [3:0] {S_FETCH, S_DECODE, S_SRCMEM, S_SRCIO, S_EXEC, S_TICK, S_END, S_HALT,
                              S_CFETCH, S_CSRC, S_FWAIT} state_t;

    state_t      state;
    logic [15:0] r [16];
    logic        z, c, m, ion, pcs;
    logic [15:0] ir, pc_at, val;
    logic        src_xfer, dst_xfer;      // source / destination transfer happened

    // Model C/D state
    logic [15:0] page, ppc, d2, rpt_word, rpt_pc, fbuf, csrc_addr;
    logic [7:0]  rpt_next, rpt_left;
    logic        shadow, rep, paged_f;

    localparam logic [6:0] PSW_DEV = 7'o001;
    wire mc = model >= 2'd2;              // Model C or D
    wire md = model == 2'd3;              // Model D
    function automatic logic internal_dev(input logic [6:0] d);
        internal_dev = (mc && (d == 7'o002 || d == 7'o010)) || (md && (d == 7'o011 || d == 7'o057));
    endfunction
    wire paged_now = md && pcs && page[15:8] != 8'd0;

    // ---------------------------------------------------------------- decode
    wire [3:0]  pcr  = pcs ? 4'o17 : 4'o16;
    // the instruction word in DECODE: repeated, or fetched (from BRAM via
    // S_FWAIT, or from a page) into fbuf. The internal memory is 100+ block
    // RAMs behind an output multiplexer: its data is only ever registered
    // (fbuf, val), never decoded in the same clock (timing).
    wire [15:0] fword = rep ? ir : fbuf;
    wire [7:0]  sbyte = (state == S_DECODE) ? fword[7:0] : ir[7:0];
    wire [7:0]  dbyte = ir[15:8];
    wire [3:0]  sreg = sbyte[3:0];
    wire [3:0]  dreg = dbyte[3:0];
    wire [3:0]  acc  = {2'b00, dbyte[1:0]};   // accumulator R0-R3

    // register as seen after the fetch's PC increment (none for a repeat)
    function automatic logic [15:0] rd(input logic [3:0] i);
        rd = (i == pcr && !rep) ? r[i] + 16'd1 : r[i];
    endfunction

    wire [15:0] imm6 = {{10{sbyte[5]}}, sbyte[5:0]};

    function automatic logic cond(input logic [2:0] cc);
        case (cc)
            3'd0: cond = 1'b1;
            3'd1: cond = z;
            3'd2: cond = c;
            3'd3: cond = m;
            3'd4: cond = 1'b0;
            3'd5: cond = !z;
            3'd6: cond = !c;
            default: cond = !m;
        endcase
    endfunction

    // highest set bit (D2 priority encoder)
    function automatic logic [3:0] msb(input logic [15:0] v);
        msb = 4'd0;
        for (int i = 0; i < 16; i++) if (v[i]) msb = 4'(i);
    endfunction

    // 260-277: shift with add, add/subtract with carry (Model C)
    wire [15:0] bs_res   = {r[acc][7:0], r[acc][15:8]} | val;
    wire [15:0] sh_sum   = {1'b0, r[acc][15:1]} + val;
    wire [16:0] adc_sum  = {1'b0, r[acc]} + {1'b0, val} + {16'd0, c};
    wire [16:0] sbb_sub  = {1'b0, val} + {16'd0, !c};
    wire [15:0] sbb_diff = r[acc] - sbb_sub[15:0];

    // ------------------------------------------------------------------- ALU
    // Result and flags for an arithmetic/logical op (table 3). Flags not
    // affected keep their value (C after LOA/AND/XOR/OR/LCM: CHOICE).
    logic [15:0] alu_res;
    logic        alu_z, alu_c, alu_m;
    logic [16:0] sum;
    always_comb begin
        logic [15:0] a;
        logic [2:0]  op;
        a  = r[acc];
        op = (dbyte < 8'o240) ? dbyte[4:2] : {1'b0, dbyte[3:2]};   // TEST: LOA/AND/ADD/SUB
        alu_c = c;
        sum   = 17'd0;
        case (op)
            3'd0: alu_res = val;
            3'd1: alu_res = a & val;
            3'd2: begin sum = {1'b0, a} + {1'b0, val}; alu_res = sum[15:0]; alu_c = sum[16]; end
            3'd3: begin alu_res = a - val; alu_c = (a >= val); end
            3'd4: alu_res = a ^ val;
            3'd5: begin alu_res = {a[14:0], a[15]}; alu_c = a[15]; end
            3'd6: alu_res = a | val;
            default: alu_res = ~val;
        endcase
        alu_z = (op == 3'd5) ? z : (alu_res == 16'd0);   // RTL leaves Z
        alu_m = alu_res[15];
    end

    // --------------------------------------------------------------- outputs
    always_comb begin
        mem_addr  = r[pcr];
        mem_we    = 1'b0;
        mem_wdata = val;
        io_rd     = 1'b0;
        io_wr     = 1'b0;
        io_dev    = ir[6:0];
        io_wdata  = val;
        irq_sample = 1'b0;
        irq_psw    = 1'b0;
        cm_rd     = 1'b0;
        cm_addr   = {page[15:8], r[pcr]};
        case (state)
            S_FETCH:  mem_addr = r[pcr];
            S_CFETCH: cm_rd = 1'b1;
            S_CSRC:   begin cm_rd = 1'b1; cm_addr = {page[15:8], csrc_addr}; end
            S_DECODE: mem_addr = rd(sreg);                 // memory sources
            S_SRCIO:  begin
                if (ir[6:0] == PSW_DEV) begin irq_sample = 1'b1; irq_psw = 1'b1; end
                else if (!internal_dev(ir[6:0])) io_rd = 1'b1;
                io_dev = ir[6:0];
            end
            S_EXEC: begin
                mem_addr = r[dreg];
                if (dbyte >= 8'o340) mem_we = 1'b1;
                io_dev = dbyte[6:0];
                if (!dbyte[7] && dbyte[6:0] != PSW_DEV && !internal_dev(dbyte[6:0])) io_wr = 1'b1;
            end
            S_END: irq_sample = 1'b1;
            default: ;
        endcase
    end

    localparam logic [9:0] NS_PER_TRANSFER = 10'd333;
    always_comb begin
        tick = 1'b0;
        tick_ns = NS_PER_TRANSFER;
        if (state == S_TICK) begin
            tick = 1'b1;
            tick_ns = NS_PER_TRANSFER * ({9'd0, !rep} + {9'd0, src_xfer} + {9'd0, dst_xfer});
        end else if (io_held) begin
            tick = 1'b1;
        end
    end
    // a held read is retried (333 ns) only when the throttle allows
    assign io_held = state == S_SRCIO && io_rd && io_hold && !io_ack && !io_nosyn && !stall;

    assign instr_done = (state == S_END);
    assign instr_pc   = pc_at;
    assign instr_word = ir;
    assign halted     = (state == S_HALT);
    assign flags      = {pcs, ion, m, c, z};
    genvar gi;
    generate for (gi = 0; gi < 16; gi++) begin : g_regs
        assign regs_flat[gi*16 +: 16] = r[gi];
    end endgenerate

    // ------------------------------------------------------------ sequencer
    always_ff @(posedge clk) begin
        if (rst) begin
            state <= S_FETCH;
            halt_reason <= 2'd0;
            rep <= 1'b0;
            paged_f <= 1'b0;
            if (dbg_we) begin
                case (dbg_addr)
                    5'd16: {pcs, ion, m, c, z} <= dbg_wdata[4:0];
                    5'd17: page <= dbg_wdata & 16'hFF00;
                    5'd18: ppc <= dbg_wdata;
                    5'd19: {rpt_next, rpt_left} <= dbg_wdata;
                    5'd20: rpt_word <= dbg_wdata;
                    5'd21: rpt_pc <= dbg_wdata;
                    5'd22: d2 <= dbg_wdata;
                    5'd23: shadow <= dbg_wdata[0];
                    default: if (!dbg_addr[4]) r[dbg_addr[3:0]] <= dbg_wdata;
                endcase
            end
        end else begin
            case (state)
            S_FETCH: if (!stall) begin
                rep <= rpt_left != 8'd0;
                paged_f <= 1'b0;
                if (rpt_left != 8'd0) begin                       // repeat: no fetch
                    pc_at <= rpt_pc;
                    state <= S_DECODE;
                end else begin
                    pc_at <= r[pcr];
                    state <= paged_now ? S_CFETCH : S_FWAIT;
                end
            end

            S_FWAIT: begin                                        // BRAM word -> fbuf
                fbuf <= mem_rdata;
                state <= S_DECODE;
            end

            S_CFETCH: if (cm_ack) begin                           // Model D page fetch
                fbuf <= cm_rdata;
                paged_f <= 1'b1;
                state <= S_DECODE;
            end

            S_DECODE: begin
                ir <= fword;
                if (rep) rpt_left <= rpt_left - 8'd1;
                else begin
                    r[pcr] <= r[pcr] + 16'd1;
                    if (rpt_next != 8'd0) begin                   // arm the repeat
                        rpt_left <= rpt_next;
                        rpt_next <= 8'd0;
                        rpt_word <= fword;
                        rpt_pc <= r[pcr];
                    end
                end
                src_xfer <= sbyte[7:6] != 2'b10;
                dst_xfer <= 1'b1;
                state <= S_EXEC;
                if (!sbyte[7]) state <= S_SRCIO;
                else if (sbyte[7:6] == 2'b10) val <= imm6;
                else begin
                    if (!sbyte[5]) val <= rd(sreg);              // register
                    else if (paged_now && sreg == pcr) begin     // literal from the page
                        csrc_addr <= rd(sreg);
                        state <= S_CSRC;
                    end else state <= S_SRCMEM;                  // memory
                    if (sbyte[4]) begin                          // post-increment
                        r[sreg] <= rd(sreg) + 16'd1;
                    end
                end
            end

            S_SRCMEM: begin
                val <= mem_rdata;
                state <= S_EXEC;
            end

            S_CSRC: if (cm_ack) begin
                val <= cm_rdata;
                state <= S_EXEC;
            end

            S_SRCIO: begin
                if (ir[6:0] == PSW_DEV) begin
                    val <= {irq, ion & pcs, m, c, z};
                    state <= S_EXEC;
                end else if (internal_dev(ir[6:0])) begin
                    case (ir[6:0])
                        7'o002:  val <= d2 == 16'd0 ? 16'd0 : {11'd0, msb(d2), 1'b0};
                        7'o010:  val <= ppc;
                        7'o011:  val <= page;
                        default: val <= d57;
                    endcase
                    state <= S_EXEC;
                end else if (io_nosyn) begin
                    halt_reason <= 2'd1;
                    state <= S_HALT;
                end else if (io_ack) begin
                    val <= io_rdata;
                    state <= S_EXEC;
                end
            end

            S_EXEC: begin
                state <= S_TICK;
                if (!dbyte[7]) begin                              // I/O destination
                    if (dbyte[6:0] == PSW_DEV) begin
                        z <= val[0]; c <= val[1]; m <= val[2];
                        pcs <= val[5];
                        if (!val[5]) ion <= 1'b0;
                        else if (val[4]) ion <= val[3];
                        if (mc) shadow <= 1'b1;
                    end else if (internal_dev(dbyte[6:0])) begin
                        case (dbyte[6:0])
                            7'o002:  d2 <= val;
                            7'o010:  rpt_next <= val[7:0];
                            7'o011:  page <= val & 16'hFF00;
                            default: ;                            // D57: read only
                        endcase
                    end else if (io_nosyn) begin
                        halt_reason <= 2'd2;
                        state <= S_HALT;
                    end else if (!io_ack) begin
                        state <= S_EXEC;                          // wait for SYN
                    end
                end else if (dbyte < 8'o260) begin                // ALU (200-237), TEST (240-257)
                    if (dbyte < 8'o240) r[acc] <= alu_res;
                    z <= alu_z; c <= alu_c; m <= alu_m;
                end else if (dbyte < 8'o300) begin                // 260-277
                    case (dbyte[3:2])
                        2'd0: begin                               // BSOR
                            r[acc] <= bs_res;
                            z <= bs_res == 16'd0;
                            m <= bs_res[15];
                        end
                        2'd1: begin                               // SHRA
                            r[acc] <= sh_sum;
                            z <= sh_sum == 16'd0;
                            m <= sh_sum[15];
                            c <= r[acc][0];
                        end
                        2'd2: if (mc) begin                       // ADC
                            r[acc] <= adc_sum[15:0];
                            c <= adc_sum[16];
                            z <= adc_sum[15:0] == 16'd0;
                            m <= adc_sum[15];
                        end
                        default: if (mc) begin                    // SBB
                            r[acc] <= sbb_diff;
                            c <= {1'b0, r[acc]} >= sbb_sub;
                            z <= sbb_diff == 16'd0;
                            m <= sbb_diff[15];
                        end
                    endcase
                end else if (dbyte < 8'o320) begin                // register
                    r[dreg] <= val;
                end else if (dbyte < 8'o340) begin                // transfers
                    if (cond(dbyte[2:0])) begin
                        r[pcr] <= dbyte[3] ? r[pcr] + val : val;
                        if (!dbyte[3]) begin                      // absolute: the link
                            ppc <= r[pcr];
                            if (mc) shadow <= 1'b1;
                        end
                    end else
                        dst_xfer <= 1'b0;                         // no destination write
                end else begin                                    // memory (write above)
                    if (dbyte[4])
                        r[dreg] <= (mc && dreg == 4'o12) ? r[dreg] - 16'd1   // MR12D
                                                         : r[dreg] + 16'd1;
                end
            end

            S_TICK: state <= S_END;

            S_END: begin
                if (halt_req) begin
                    halt_reason <= 2'd3;
                    state <= S_HALT;
                end else begin
                    state <= S_FETCH;
                    if (rpt_left != 8'd0 || rpt_next != 8'd0) ;  // no interrupt inside a repeat
                    else if (shadow) shadow <= 1'b0;             // nor right after PCW / jump
                    else if (ion && pcs && irq != 12'd0) begin   // interrupt entry
                        ion <= 1'b0;
                        pcs <= 1'b0;
                        ppc <= r[4'o17];
                    end
                end
            end

            default: ;                                            // S_HALT
            endcase
        end
    end

endmodule
