//----------------------------------------------------------------------
// nchan — N independent 1-bit latch channels, one block. Exercises the I-9 `count`
// feature: one agent replicated N times, each bound to a slice of the DUT's VECTORED
// ports (the alert_handler topology — N alert lines into one block). Per channel: latch
// `d[i]` into `q[i]` when `v[i]`.
//----------------------------------------------------------------------
module nchan #(parameter int N = 3) (
  input  logic         clk,
  input  logic         rst_n,
  input  logic [N-1:0] d,   // per-channel data
  input  logic [N-1:0] v,   // per-channel valid
  output logic [N-1:0] q    // per-channel latched value
);
  for (genvar i = 0; i < N; i++) begin : gen_ch
    always_ff @(posedge clk or negedge rst_n)
      if (!rst_n)    q[i] <= 1'b0;
      else if (v[i]) q[i] <= d[i];
  end
endmodule
