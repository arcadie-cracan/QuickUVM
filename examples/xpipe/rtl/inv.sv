//----------------------------------------------------------------------
// inv — stg2 stage 2: dout = ~din (combinational). Its din is driven by stg1's
// `add` via a top cross-level connection, so its agent is passive.
//----------------------------------------------------------------------
module inv (
  output logic [7:0] dout,
  input        [7:0] din
  );
  assign dout = ~din;
endmodule
