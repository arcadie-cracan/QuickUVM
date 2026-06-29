//----------------------------------------------------------------------
// splitter — one request stream, two DIFFERENT-typed response channels
// (QuickUVM A2 multi-transaction-type example DUT).
//
// Each valid request {req_id, req_data} produces, on its own latency, a response
// on BOTH channels carrying the same tag:
//   - channel A (sum):  a_sum  = req_data + req_id     (a wide payload)
//   - channel B (flag): b_flag = (req_data >= 8'h80)   (a 1-bit payload)
// The two channels are different transaction types, so each gets its own typed
// scoreboard (predictor/comparator) — that is the multi-transaction-type case.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module splitter #(
    parameter int LA  = 2,  // channel A latency
    parameter int LB  = 3,  // channel B latency
    parameter int IDW = 4,
    parameter int DW  = 8
) (
    input  logic           clk,
    input  logic           rst_n,
    // request stream (driven)
    input  logic           req_valid,
    input  logic [IDW-1:0] req_id,
    input  logic [DW-1:0]  req_data,
    // channel A: sum (observed)
    output logic           a_valid,
    output logic [IDW-1:0] a_id,
    output logic [DW-1:0]  a_sum,
    // channel B: flag (observed)
    output logic           b_valid,
    output logic [IDW-1:0] b_id,
    output logic           b_flag
);
  logic          av  [LA], bv  [LB];
  logic [IDW-1:0] aid [LA], bid [LB];
  logic [DW-1:0]  asum[LA];
  logic           bfl [LB];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < LA; i++) begin
        av[i] <= 1'b0; aid[i] <= '0; asum[i] <= '0;
      end
      for (int i = 0; i < LB; i++) begin
        bv[i] <= 1'b0; bid[i] <= '0; bfl[i] <= 1'b0;
      end
    end else begin
      av[0]   <= req_valid;
      aid[0]  <= req_id;
      asum[0] <= req_data + {{(DW - IDW) {1'b0}}, req_id};
      for (int i = 1; i < LA; i++) begin
        av[i] <= av[i-1]; aid[i] <= aid[i-1]; asum[i] <= asum[i-1];
      end
      bv[0]   <= req_valid;
      bid[0]  <= req_id;
      bfl[0]  <= (req_data >= 8'h80);
      for (int i = 1; i < LB; i++) begin
        bv[i] <= bv[i-1]; bid[i] <= bid[i-1]; bfl[i] <= bfl[i-1];
      end
    end
  end

  assign a_valid = av[LA-1];
  assign a_id    = aid[LA-1];
  assign a_sum   = asum[LA-1];
  assign b_valid = bv[LB-1];
  assign b_id    = bid[LB-1];
  assign b_flag  = bfl[LB-1];
endmodule
