// Simulation top for CPU-only lockstep (M4.3): the CPU and 64K words of
// synchronous internal memory with a load port. Every device access goes
// out on dev_* and the C++ bench (hdl/sim/lockstep.cpp) answers it from a
// trace recorded by the Python simulator. Same port names as
// able_sys_top so one bench drives both.
module able_sim_top (
    input  logic        clk,
    input  logic        rst,
    input  logic        ld_mem_we,
    input  logic [15:0] ld_mem_addr,
    input  logic [15:0] ld_mem_data,
    input  logic        dbg_we,
    input  logic [4:0]  dbg_addr,
    input  logic [15:0] dbg_wdata,

    output logic        dev_rd,
    output logic        dev_wr,
    output logic [6:0]  dev_num,
    output logic [15:0] dev_wdata,
    input  logic [15:0] dev_rdata,
    input  logic        dev_ack,
    input  logic        dev_nosyn,
    input  logic        dev_hold,
    input  logic [15:4] dev_irq,
    output logic        irq_sample,
    output logic        irq_psw,
    output logic [15:4] irq_all,
    output logic        io_held,
    output logic        tick,
    output logic [9:0]  tick_ns,
    input  logic        halt_req,
    output logic        halted,
    output logic [1:0]  halt_reason,
    output logic        instr_done,
    output logic [15:0] instr_pc,
    output logic [15:0] instr_word,
    output logic [255:0] regs_flat,
    output logic [4:0]  flags,
    output logic        mon_valid,
    output logic        mon_wr,
    output logic [6:0]  mon_dev,
    output logic [15:0] mon_data
);
    logic [15:0] mem [65536];
    logic [15:0] mem_addr, mem_wdata, mem_rdata;
    logic        mem_we;

    always_ff @(posedge clk) begin
        if (rst && ld_mem_we) mem[ld_mem_addr] <= ld_mem_data;
        else if (mem_we) mem[mem_addr] <= mem_wdata;
        mem_rdata <= mem[mem_addr];
    end

    able_cpu cpu (
        .clk, .rst, .mem_addr, .mem_we, .mem_wdata, .mem_rdata,
        .io_rd(dev_rd), .io_wr(dev_wr), .io_dev(dev_num), .io_wdata(dev_wdata),
        .io_rdata(dev_rdata), .io_ack(dev_ack), .io_nosyn(dev_nosyn), .io_hold(dev_hold),
        .io_held, .tick, .tick_ns,
        .irq(dev_irq), .irq_sample, .irq_psw,
        .halt_req, .halted, .halt_reason,
        .instr_done, .instr_pc, .instr_word,
        .dbg_we, .dbg_addr, .dbg_wdata, .regs_flat, .flags
    );
    assign irq_all   = dev_irq;
    assign mon_valid = (dev_rd || dev_wr) && dev_ack && !dev_nosyn;
    assign mon_wr    = dev_wr;
    assign mon_dev   = dev_num;
    assign mon_data  = dev_wr ? dev_wdata : dev_rdata;
endmodule
