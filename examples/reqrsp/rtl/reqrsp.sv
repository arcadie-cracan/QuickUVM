//----------------------------------------------------------------------
// reqrsp — a tagged request/response unit (QuickUVM A2 / two-stream example DUT).
//
// A valid-qualified request {req_id, req_data} enters; some cycles later the
// matching response {rsp_id, rsp_data = req_data + req_id} leaves, carrying the
// same tag. Requests are routed by req_id[0] to one of two latency lanes, so a
// response from the fast lane can OVERTAKE an earlier response from the slow lane:
// the response stream is REORDERED vs the request stream, and the scoreboard must
// match by tag (match: out_of_order, match_key: rsp_id).
//
// No-collision invariant: with the two lane latencies differing by an ODD number
// and requests paced one every two cycles (the req driver does this), the two
// lanes can never complete on the same cycle, so the outputs need only an OR-mux,
// no arbiter. The assertion below guards the invariant.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module reqrsp #(
    parameter int LAT0 = 2,  // even-id lane latency
    parameter int LAT1 = 5,  // odd-id lane latency (LAT1-LAT0 must be ODD)
    parameter int IDW  = 4,
    parameter int DW   = 8
) (
    input  logic           clk,
    input  logic           rst_n,
    // request stream (driven)
    input  logic           req_valid,
    input  logic [IDW-1:0] req_id,
    input  logic [DW-1:0]  req_data,
    // response stream (observed), reordered across the two lanes
    output logic           rsp_valid,
    output logic [IDW-1:0] rsp_id,
    output logic [DW-1:0]  rsp_data
);
  localparam int PW = IDW + DW;  // payload carried through a lane: {id, result}
  logic [PW-1:0] pin;
  assign pin = {req_id, (req_data + {{(DW - IDW) {1'b0}}, req_id})};  // transform

  // two latency lanes (shift pipelines), routed by req_id[0]
  logic          v0 [LAT0], v1 [LAT1];
  logic [PW-1:0] p0 [LAT0], p1 [LAT1];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < LAT0; i++) begin v0[i] <= 1'b0; p0[i] <= '0; end
      for (int i = 0; i < LAT1; i++) begin v1[i] <= 1'b0; p1[i] <= '0; end
    end else begin
      v0[0] <= req_valid && (req_id[0] == 1'b0);  // even ids -> lane 0
      p0[0] <= pin;
      for (int i = 1; i < LAT0; i++) begin v0[i] <= v0[i-1]; p0[i] <= p0[i-1]; end
      v1[0] <= req_valid && (req_id[0] == 1'b1);  // odd ids -> lane 1
      p1[0] <= pin;
      for (int i = 1; i < LAT1; i++) begin v1[i] <= v1[i-1]; p1[i] <= p1[i-1]; end
    end
  end

  // The two lanes never complete on the same cycle (see header) -> OR-mux.
  logic lane0_done, lane1_done;
  assign lane0_done = v0[LAT0-1];
  assign lane1_done = v1[LAT1-1];
  assign rsp_valid = lane0_done | lane1_done;
  assign {rsp_id, rsp_data} = lane0_done ? p0[LAT0-1] : p1[LAT1-1];

  // Guard the no-collision invariant (both lanes completing the same cycle would
  // silently drop a response in the OR-mux).
  assert property (@(posedge clk) disable iff (!rst_n) !(lane0_done && lane1_done))
  else $error("reqrsp: both lanes completed the same cycle (pacing/latency invariant broken)");
endmodule
