//----------------------------------------------------------------------
// fifo — synchronous FIFO with a registered read data path.
//
// Two interfaces (a write port and a read port), so it is the multi-agent
// example for QuickUVM's C2 (virtual sequencer + virtual sequences).
//
// Registered read: on a committed read, `rd_data` is flopped and becomes valid
// the NEXT cycle. That matches the generated registered monitor, which pairs a
// transaction's inputs (sampled at posedge N) with its outputs (sampled just
// before posedge N+1) — so `rd_en` at N pairs with the popped `rd_data` at N+1.
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module fifo #(
  parameter int DW    = 8,
  parameter int DEPTH = 32
) (
  input  logic          clk,
  input  logic          rst_n,
  // write port
  input  logic          wr_en,
  input  logic [DW-1:0] wr_data,
  output logic          full,
  // read port
  input  logic          rd_en,
  output logic [DW-1:0] rd_data,
  output logic          empty
);
  localparam int AW = $clog2(DEPTH);

  logic [DW-1:0] mem [DEPTH];
  logic [AW:0]   wptr, rptr;          // one extra bit to tell full from empty
  logic          do_wr, do_rd;

  assign empty = (wptr == rptr);
  assign full  = (wptr[AW] != rptr[AW]) && (wptr[AW-1:0] == rptr[AW-1:0]);
  assign do_wr = wr_en && !full;
  assign do_rd = rd_en && !empty;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr    <= '0;
      rptr    <= '0;
      rd_data <= '0;
    end else begin
      if (do_wr) begin
        mem[wptr[AW-1:0]] <= wr_data;
        wptr              <= wptr + 1'b1;
      end
      if (do_rd) begin
        rd_data <= mem[rptr[AW-1:0]];   // registered: valid next cycle
        rptr    <= rptr + 1'b1;
      end
    end
  end
endmodule
