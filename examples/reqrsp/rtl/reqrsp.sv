//----------------------------------------------------------------------
// reqrsp — a tagged request/response unit (QuickUVM A2 / two-stream example DUT).
//
// A valid-qualified request {req_id, req_data} enters; LAT cycles later the
// matching response {rsp_id, rsp_data = req_data + req_id} leaves, carrying the
// same tag. This slice is a SINGLE in-order lane (responses preserve request
// order); the A2 out-of-order slice adds a second lane with a different latency
// so responses can overtake and must be matched by tag.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module reqrsp #(
    parameter int LAT = 2,
    parameter int IDW = 4,
    parameter int DW  = 8
) (
    input  logic           clk,
    input  logic           rst_n,
    // request stream (driven)
    input  logic           req_valid,
    input  logic [IDW-1:0] req_id,
    input  logic [DW-1:0]  req_data,
    // response stream (observed), LAT cycles later, in order
    output logic           rsp_valid,
    output logic [IDW-1:0] rsp_id,
    output logic [DW-1:0]  rsp_data
);
  // single in-order lane: a LAT-deep {valid, id, result} shift pipeline.
  logic           v  [LAT];
  logic [IDW-1:0] iq [LAT];
  logic [DW-1:0]  rq [LAT];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < LAT; i++) begin
        v[i]  <= 1'b0;
        iq[i] <= '0;
        rq[i] <= '0;
      end
    end else begin
      v[0]  <= req_valid;
      iq[0] <= req_id;
      rq[0] <= req_data + {{(DW - IDW) {1'b0}}, req_id};  // transform: data + id
      for (int i = 1; i < LAT; i++) begin
        v[i]  <= v[i-1];
        iq[i] <= iq[i-1];
        rq[i] <= rq[i-1];
      end
    end
  end

  assign rsp_valid = v[LAT-1];
  assign rsp_id    = iq[LAT-1];
  assign rsp_data  = rq[LAT-1];
endmodule
