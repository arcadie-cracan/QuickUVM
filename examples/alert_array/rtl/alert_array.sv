//----------------------------------------------------------------------
// alert_array — N alert channels into one block, the alert_handler topology: each channel
// PINGS its sender (which must respond — reactive) and RECEIVES alerts it raises with a
// payload (proactive). Exercises the COMPOSITION of `count` (N replicas into one vectored
// DUT) and the hybrid agent (`proactive: true`): N hybrid alert-senders, each answering
// its own ping AND raising its own alerts. See docs/alert_array_assessment.md.
//----------------------------------------------------------------------
module alert_array #(
  parameter int N  = 3,
  parameter int DW = 4          // alert-payload width per channel
) (
  input  logic            clk,
  input  logic            rst_n,
  output logic [N-1:0]    ping,        // per-channel ping (the sender answers)
  input  logic [N-1:0]    resp,        // per-channel ping response (the sender drives)
  input  logic [N-1:0]    alert,       // per-channel alert pulse (the sender drives)
  input  logic [N*DW-1:0] adata,       // per-channel alert payload (the sender drives)
  output logic [N*DW-1:0] last_adata   // per-channel latched payload
);
  // Ping every channel every 4 cycles. The sender's `resp` is not read here — the
  // testbench proves each responder alive by draining its own ping FIFO, not by this net.
  logic [1:0] pcnt;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pcnt <= '0;
      ping <= '0;
    end else begin
      pcnt <= pcnt + 1'b1;
      ping <= {N{(pcnt == 2'd3)}};
    end
  end

  // Per-channel: latch the payload of each raised alert.
  for (genvar i = 0; i < N; i++) begin : gen_ch
    always_ff @(posedge clk or negedge rst_n)
      if (!rst_n)         last_adata[i*DW +: DW] <= '0;
      else if (alert[i])  last_adata[i*DW +: DW] <= adata[i*DW +: DW];
  end
endmodule
