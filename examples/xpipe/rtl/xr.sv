//----------------------------------------------------------------------
// xr — stg2's independent second block: dout = din ^ 8'hA5 (combinational).
//----------------------------------------------------------------------
module xr (
  output logic [7:0] dout,
  input        [7:0] din
  );
  assign dout = din ^ 8'hA5;
endmodule
