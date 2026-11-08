// Simulation top for lockstep checks (M4.3): the CPU, 64K words of
// synchronous internal memory with a load port, and the CPU's I/O bus
// brought out to the C++ test bench (hdl/sim/lockstep.cpp), which answers
// every device access from a trace recorded by the Python simulator.

module able_sim_top (
    input  logic        clk,
    input  logic        rst,
    input  logic        ld_we,         // memory load while in reset
    input  logic [15:0] ld_addr,
    input  logic [15:0] ld_data,
    input  logic        dbg_we,
    input  logic [4:0]  dbg_addr,
    input  logic [15:0] dbg_wdata,

    output logic        io_rd,
    output logic        io_wr,
    output logic [6:0]  io_dev,
    output logic [15:0] io_wdata,
    input  logic [15:0] io_rdata,
    input  logic        io_ack,
    input  logic        io_nosyn,
    input  logic [15:4] irq,
    output logic        irq_sample,
    output logic        irq_psw,
    input  logic        halt_req,
    output logic        halted,
    output logic [1:0]  halt_reason,
    output logic        instr_done,
    output logic [15:0] instr_pc,
    output logic [15:0] instr_word,
    output logic [255:0] regs_flat,
    output logic [4:0]  flags
);
    logic [15:0] mem [65536];
    logic [15:0] mem_addr, mem_wdata, mem_rdata;
    logic        mem_we;

    always_ff @(posedge clk) begin
        if (rst && ld_we) mem[ld_addr] <= ld_data;
        else if (mem_we) mem[mem_addr] <= mem_wdata;
        mem_rdata <= mem[mem_addr];
    end

    able_cpu cpu (.*);
endmodule
