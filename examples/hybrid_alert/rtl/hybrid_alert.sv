//----------------------------------------------------------------------
// hybrid_alert — a tiny alert-receiver, shrunk from OpenTitan's prim_alert_receiver
// idea, that exercises a HYBRID testbench agent (docs/hybrid_agent_assessment.md).
//
// The DUT does two independent things to the TB's ONE agent:
//   * it PINGS the sender periodically (`ping` pulse) and expects a response — the agent
//     must ANSWER (a reactive obligation, like a liveness ping);
//   * it RECEIVES alerts the sender raises spontaneously (`alert` pulse + `adata`) and
//     latches the payload (`last_adata`) + counts them (`alert_cnt`).
//
// So the agent is a HYBRID: a responder (answers pings) AND an initiator (raises alerts)
// at once — the shape QuickUVM's `proactive: true` adds. The reactive path's liveness is
// checked TB-side by the request-FIFO drain (a dead responder can't be caught by the
// driver's drive count, which the proactive alerts inflate); the proactive path is checked
// by a scoreboard against `last_adata`.
//----------------------------------------------------------------------
module hybrid_alert (
  input  logic        clk,
  input  logic        rst_n,
  // reactive: the DUT pings the sender and expects a response
  output logic        ping,        // request pulse (the agent samples this)
  input  logic        resp,        // the sender's ping response (the agent drives this)
  output logic [7:0]  resp_cnt,    // responses seen (observability; liveness is TB-side)
  // proactive: the sender raises alerts carrying a payload
  input  logic        alert,       // alert pulse (the agent drives this)
  input  logic [7:0]  adata,       // alert payload (the agent drives this)
  output logic [7:0]  last_adata,  // the payload of the most recent alert (latched)
  output logic [15:0] alert_cnt    // number of alerts received
);
  // Ping the sender every 4 cycles.
  logic [1:0] pcnt;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pcnt <= '0;
      ping <= 1'b0;
    end else begin
      pcnt <= pcnt + 1'b1;
      ping <= (pcnt == 2'd3);
    end
  end

  // Count the sender's ping responses (observability only — the testbench proves the
  // responder alive by draining every ping, not by reading this).
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n)   resp_cnt <= '0;
    else if (resp) resp_cnt <= resp_cnt + 1'b1;

  // Latch the payload of each raised alert, and count them.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      last_adata <= '0;
      alert_cnt  <= '0;
    end else if (alert) begin
      last_adata <= adata;
      alert_cnt  <= alert_cnt + 1'b1;
    end
  end
endmodule
