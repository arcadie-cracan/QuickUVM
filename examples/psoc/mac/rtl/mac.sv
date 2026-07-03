//----------------------------------------------------------------------
// mac — a parameterized combinational block: dout = din << 1 at width W.
//----------------------------------------------------------------------
module mac #(parameter int W = 8) (
  output logic [W-1:0] dout,
  input        [W-1:0] din
  );

  assign dout = din << 1;

endmodule
