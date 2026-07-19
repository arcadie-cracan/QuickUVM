//----------------------------------------------------------------------
// inv — pipeline stage 2: dout = ~din (combinational). Its din is driven by
// stage 1's dout (a top-level cross-block connection), so its agent is passive.
//----------------------------------------------------------------------
module inv (
  output logic [7:0] dout,
  input        [7:0] din
  );
  assign dout = ~din;
endmodule
