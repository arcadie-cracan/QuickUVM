//----------------------------------------------------------------------
// twowidth — a trivial parameterized combinational DUT: dout = din + 1 at
// width W. The point of the example is not the DUT but that ONE parameterized
// agent VIP is instantiated twice (at W=8 and W=16) in a single bench, each
// instance with its own interface, DUT and scoreboard.
//----------------------------------------------------------------------
module twowidth #(parameter int W = 8) (
  output logic [W-1:0] dout,
  input        [W-1:0] din
  );

  assign dout = din + 1'b1;

endmodule
