//----------------------------------------------------------------------
// dbl — stg1's independent second block: dout = din << 1 (combinational).
//----------------------------------------------------------------------
module dbl (
  output logic [7:0] dout,
  input        [7:0] din
  );
  assign dout = din << 1;
endmodule
