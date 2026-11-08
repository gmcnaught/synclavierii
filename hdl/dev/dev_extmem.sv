// D60-D63 external memory interface (sim/devices/extmem.py).
//   D60 sector (read/write; a write also sets the word to 0)
//   D61 word within the 256-word sector (read/write)
//   D62 data, D63 data with auto-increment (word, carrying into the sector)
// Beyond `sectors` reads give 177777 and writes are ignored (CHOICE, as
// Python). The words live in an external RAM (SDRAM on the board, an array
// in simulation) behind a request/ack port; waiting for it costs no
// simulated time.
module dev_extmem (
    input  logic        clk,
    input  logic        rst,
    input  logic        sel,
    input  logic        rd,
    input  logic        wr,
    input  logic [1:0]  reg_sel,      // 0 D60, 1 D61, 2 D62, 3 D63
    input  logic [15:0] wdata,
    output logic [15:0] rdata,
    output logic        ack,
    input  logic [16:0] sectors,      // installed size (1..65536)

    output logic [23:0] xm_addr,
    output logic        xm_rd,
    output logic        xm_wr,
    output logic [15:0] xm_wdata,
    input  logic [15:0] xm_rdata,
    input  logic        xm_ack,

    input  logic        ld_we,        // state load (simulation): 0 sector, 1 word
    input  logic [3:0]  ld_addr,
    input  logic [31:0] ld_data
);
    logic [15:0] sector;
    logic [7:0]  word;

    wire data_reg = reg_sel[1];
    wire in_range   = {1'b0, sector} < sectors;
    wire use_ram  = sel && data_reg && in_range;

    assign xm_addr  = {sector, word};
    assign xm_rd    = use_ram && rd;
    assign xm_wr    = use_ram && wr;
    assign xm_wdata = wdata;
    assign ack      = sel && (use_ram ? xm_ack : 1'b1);
    always_comb begin
        case (reg_sel)
            2'd0: rdata = sector;
            2'd1: rdata = {8'd0, word};
            default: rdata = in_range ? xm_rdata : 16'hFFFF;
        endcase
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            if (ld_we && ld_addr == 4'd0) sector <= ld_data[15:0];
            if (ld_we && ld_addr == 4'd1) word <= ld_data[7:0];
        end else if (ack && (rd || wr)) begin
            if (wr && reg_sel == 2'd0) begin
                sector <= wdata;
                word <= 8'd0;
            end else if (wr && reg_sel == 2'd1) begin
                word <= wdata[7:0];
            end else if (reg_sel == 2'd3) begin
                word <= word + 8'd1;
                if (word == 8'hFF) sector <= sector + 16'd1;
            end
        end
    end
endmodule
