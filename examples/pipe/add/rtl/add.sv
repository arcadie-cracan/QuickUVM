//----------------------------------------------------------------------
// add — pipeline stage 1: dout = din + 1 (combinational).
//----------------------------------------------------------------------
module add (
  output logic [7:0] dout,
  input        [7:0] din
  );
  assign dout = din + 1'b1;
endmodule
