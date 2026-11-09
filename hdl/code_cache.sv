// Model D code cache: a direct-mapped cache of external-memory words for
// the CPU's page fetches (able_cpu.sv cm_*), in front of the external RAM
// port it shares with D60-D63. Without it every instruction on an
// external page waits for DDR3, and SYN-5.3 runs slower than real time.
//
// 2^INDEX_BITS words; a line is one word with its tag (address bits above
// bit INDEX_BITS) and a valid bit. The index folds the tag into the low
// address bits (a[13:0] ^ a[23:14] << 4 for 14 bits): every external page
// starts with the same page-switch stub and SYN-5.3's idle loop runs on five
// pages, so the plain low bits made the pages evict each other (idle: 1717
// distinct words, 300 misses per ms with plain low bits, 6 with the fold;
// recorded with the simulator). The tag and the index give back the address. Every write through the shared port (D62/D63,
// x_wr) also writes the cache line it maps to (write-through, allocate), so
// the cache never holds a stale word. After reset the valid bits are
// cleared, one line per clock (a fetch waits for that, 2^INDEX_BITS clocks). A hit answers
// the clock after the request; a miss reads the RAM and fills the line.
// The cache changes no behaviour, only how long a fetch waits (which costs
// no simulated time).
module code_cache #(
    parameter int INDEX_BITS = 14
) (
    input  logic        clk,
    input  logic        rst,

    input  logic [23:0] cm_addr,       // CPU code port
    input  logic        cm_rd,
    output logic [15:0] cm_rdata,
    output logic        cm_ack,

    input  logic [23:0] wr_addr,       // writes through the shared port (snooped)
    input  logic        wr_en,         // one clock per completed write
    input  logic [15:0] wr_data,

    output logic [23:0] m_addr,        // the RAM, for misses
    output logic        m_rd,
    input  logic [15:0] m_rdata,
    input  logic        m_ack
);
    localparam int N = 1 << INDEX_BITS;
    localparam int TAG_BITS = 24 - INDEX_BITS;

    logic [15:0]           data_ram [N];
    logic [TAG_BITS:0]     tag_ram  [N];      // {valid, tag}

    typedef enum logic [1:0] {C_CLEAR, C_IDLE, C_LOOK, C_MISS} cstate_t;
    cstate_t state;
    logic [INDEX_BITS-1:0] clr;
    logic [15:0]           q_data;
    logic [TAG_BITS:0]     q_tag;
    logic [23:0]           a;                   // address being looked up

    function automatic logic [INDEX_BITS-1:0] index_of(input logic [23:0] x);
        index_of = x[INDEX_BITS-1:0] ^ INDEX_BITS'({x[23:INDEX_BITS], 4'd0});
    endfunction
    wire [INDEX_BITS-1:0] idx_w = index_of(wr_addr);
    wire [INDEX_BITS-1:0] idx_r = index_of(cm_addr);
    wire [INDEX_BITS-1:0] idx_a = index_of(a);

    // one write port (clear, fill or snooped write), one read port
    logic                  we;
    logic [INDEX_BITS-1:0] w_idx;
    logic [15:0]           w_data;
    logic [TAG_BITS:0]     w_tag;
    always_comb begin
        we = 1'b0; w_idx = idx_w; w_data = wr_data; w_tag = {1'b1, wr_addr[23:INDEX_BITS]};
        if (state == C_CLEAR) begin
            we = 1'b1; w_idx = clr; w_tag = '0;
        end else if (wr_en) begin
            we = 1'b1;
        end else if (state == C_MISS && m_ack) begin
            we = 1'b1; w_idx = idx_a; w_data = m_rdata;
            w_tag = {1'b1, a[23:INDEX_BITS]};
        end
    end
    always_ff @(posedge clk) begin
        if (we) begin
            data_ram[w_idx] <= w_data;
            tag_ram[w_idx] <= w_tag;
        end
        q_data <= data_ram[idx_r];
        q_tag <= tag_ram[idx_r];
    end

    assign m_addr = a;
    assign m_rd   = state == C_MISS;

    always_ff @(posedge clk) begin
        cm_ack <= 1'b0;
        if (rst) begin
            state <= C_CLEAR;
            clr <= '0;
        end else case (state)
            C_CLEAR: begin
                clr <= clr + 1'b1;
                if (clr == INDEX_BITS'(N - 1)) state <= C_IDLE;
            end
            C_IDLE: if (cm_rd && !cm_ack) begin
                a <= cm_addr;
                state <= C_LOOK;                    // q_* hold this line next clock
            end
            C_LOOK: begin
                // a write to the same line in between leaves q stale: miss then
                if (q_tag == {1'b1, a[23:INDEX_BITS]} && !(wr_en && idx_w == idx_a)) begin
                    cm_rdata <= q_data;
                    cm_ack <= 1'b1;
                    state <= C_IDLE;
                end else state <= C_MISS;
            end
            C_MISS: if (m_ack) begin
                cm_rdata <= m_rdata;
                cm_ack <= 1'b1;
                state <= C_IDLE;
            end
            default: state <= C_IDLE;
        endcase
    end
endmodule
