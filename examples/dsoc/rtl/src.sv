//----------------------------------------------------------------------
// src — lane's active source: dout = din + 1 (combinational).
//----------------------------------------------------------------------
module src (
  output logic [7:0] dout,
  input        [7:0] din
  );
  assign dout = din + 1'b1;
endmodule
