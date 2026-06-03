//----------------------------------------------------------------------
// priority_encoder — parameterized combinational priority encoder.
// idx = index of the highest set bit of req (MSB priority); valid = |req.
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module priority_encoder #(
  parameter int N = 8
) (
  input  logic [N-1:0]         req,
  output logic [$clog2(N)-1:0] idx,
  output logic                 valid
);
  always_comb begin
    idx   = '0;
    valid = 1'b0;
    for (int i = 0; i < N; i++) begin
      if (req[i]) begin
        idx   = ($clog2(N))'(i);   // highest set bit wins (loop runs low->high)
        valid = 1'b1;
      end
    end
  end
endmodule
