//----------------------------------------------------------------------
// sat_adder — combinational unsigned saturating adder (W=8).
// sum = min(a + b, 2**W-1); ovf = 1 when the unsaturated sum overflows W bits.
// The K0 example: its golden model is written in C and called via DPI-C.
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module sat_adder #(
  parameter int W = 8
) (
  input  logic [W-1:0] a,
  input  logic [W-1:0] b,
  output logic [W-1:0] sum,
  output logic         ovf
);
  logic [W:0] full;

  always_comb begin
    full = {1'b0, a} + {1'b0, b};
    ovf  = full[W];
    sum  = full[W] ? {W{1'b1}} : full[W-1:0];   // saturate to all-ones on overflow
  end
endmodule
