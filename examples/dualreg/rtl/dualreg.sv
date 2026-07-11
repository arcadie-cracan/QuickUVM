//----------------------------------------------------------------------
// dualreg — two registered lanes on one clock, each with its OWN agent-driven
// reset (mixed polarity, M1 multi agent-driven reset demo):
//   - lane a: adout <= adin + 1,   reset a_rst_n (ACTIVE-LOW), driven by agent a
//   - lane b: bdout <= bdin << 1,  reset b_rst   (ACTIVE-HIGH), driven by agent b
//----------------------------------------------------------------------
module dualreg (
  output logic [7:0] adout,
  input        [7:0] adin,
  input              a_rst_n,
  output logic [7:0] bdout,
  input        [7:0] bdin,
  input              b_rst,
  input              clk
  );

  always_ff @(posedge clk or negedge a_rst_n)
    if (!a_rst_n) adout <= '0;
    else          adout <= adin + 1'b1;

  always_ff @(posedge clk or posedge b_rst)
    if (b_rst) bdout <= '0;
    else       bdout <= bdin << 1;

endmodule
