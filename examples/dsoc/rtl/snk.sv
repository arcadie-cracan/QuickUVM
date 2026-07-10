//----------------------------------------------------------------------
// snk — lane's passive sink: dout = ~din (combinational). Its din is driven by
// the other lane's src via a cross-instance top connection, so its agent is
// passive.
//----------------------------------------------------------------------
module snk (
  output logic [7:0] dout,
  input        [7:0] din
  );
  assign dout = ~din;
endmodule
