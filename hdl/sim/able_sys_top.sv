// Simulation top for system lockstep (M4.4-M4.6): able_system plus RAM
// models for external memory (1M words) and the two floppies (512K words),
// each answering the clock after a request, with load ports. Devices not yet in HDL are answered by the C++ bench
// (hdl/sim/lockstep.cpp) from the recorded trace.
module able_sys_top (
    input  logic        clk,
    input  logic        rst,
    output logic        dev_rd,
    output logic        dev_wr,
    output logic [6:0]  dev_num,
    output logic [15:0] dev_wdata,
    input  logic [15:0] dev_rdata,
    input  logic        dev_ack,
    input  logic        dev_nosyn,
    input  logic        dev_hold,
    input  logic [15:4] dev_irq,
    input  logic [16:0] ext_sectors,
    input  logic        ld_xm_we,
    input  logic [19:0] ld_xm_addr,
    input  logic [15:0] ld_xm_data,
    input  logic [1:0]  fd_present,
    input  logic [1:0]  fd_protect,
    input  logic [10:0] fd_sectors0,
    input  logic [10:0] fd_sectors1,
    input  logic [3:0]  fd_spt0,
    input  logic [3:0]  fd_spt1,
    input  logic [1:0]  fd_sides0,
    input  logic [1:0]  fd_sides1,
    input  logic        ld_fd_we,
    input  logic [18:0] ld_fd_addr,
    input  logic [15:0] ld_fd_data,
    input  logic        term_rx_valid,
    input  logic [7:0]  term_rx_data,
    output logic        term_tx_valid,
    output logic [7:0]  term_tx_data,
    input  logic        halt_req,
    output logic        halted,
    output logic [1:0]  halt_reason,
    input  logic        ld_mem_we,
    input  logic [15:0] ld_mem_addr,
    input  logic [15:0] ld_mem_data,
    input  logic        dbg_we,
    input  logic [4:0]  dbg_addr,
    input  logic [15:0] dbg_wdata,
    input  logic        ld_dev_we,
    input  logic [2:0]  ld_dev_sel,
    input  logic [4:0]  ld_dev_addr,
    input  logic [31:0] ld_dev_data,
    output logic        instr_done,
    output logic [15:0] instr_pc,
    output logic [15:0] instr_word,
    output logic [255:0] regs_flat,
    output logic [4:0]  flags,
    output logic        irq_sample,
    output logic        irq_psw,
    output logic [15:4] irq_all,
    output logic        io_held,
    output logic        tick,
    output logic [9:0]  tick_ns,
    output logic        mon_valid,
    output logic        mon_wr,
    output logic [6:0]  mon_dev,
    output logic [15:0] mon_data
);
    logic [23:0] xm_addr;
    logic        xm_rd, xm_wr, xm_ack;
    logic [15:0] xm_wdata, xm_rdata;
    logic [15:0] xram [1 << 20];

    always_ff @(posedge clk) begin
        if (rst) begin
            xm_ack <= 1'b0;
            if (ld_xm_we) xram[ld_xm_addr] <= ld_xm_data;
        end else begin
            xm_ack <= (xm_rd || xm_wr) && !xm_ack;
            if (xm_wr && !xm_ack) xram[xm_addr[19:0]] <= xm_wdata;
            xm_rdata <= xram[xm_addr[19:0]];
        end
    end

    // floppy words: 2 drives x 1024 sectors x 256 words
    logic [18:0] fd_addr;
    logic        fd_rd, fd_wr, fd_ack;
    logic [15:0] fd_wdata, fd_rdata;
    logic [15:0] fram [1 << 19];
    always_ff @(posedge clk) begin
        if (rst) begin
            fd_ack <= 1'b0;
            if (ld_fd_we) fram[ld_fd_addr] <= ld_fd_data;
        end else begin
            fd_ack <= (fd_rd || fd_wr) && !fd_ack;
            if (fd_wr && !fd_ack) fram[fd_addr] <= fd_wdata;
            fd_rdata <= fram[fd_addr];
        end
    end

    able_system sys (.*);
endmodule
