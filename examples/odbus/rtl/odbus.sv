// An open-drain (wired-AND) bus device — the shape of I2C's SDA/SCL.
//
// The DUT and the testbench SHARE one wire. Neither can drive it high: each may only pull
// it LOW or RELEASE it, and a pullup makes it read 1 when everyone has let go. That is why
// two devices can pull low at the same instant with no contention — the property this
// example exists to check.

module odbus (
  input  logic clk,
  input  logic rst_n,
  inout  wire  sda,       // shared, open-drain
  output logic dut_low    // observable: is the DUT pulling low right now?
);

  logic [2:0] ctr;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) ctr <= 3'd0;
    else        ctr <= ctr + 3'd1;
  end

  // The DUT pulls the line low for 2 of every 8 cycles — so it will sometimes collide with
  // the TB pulling low, which on a wired-AND bus must be harmless.
  assign dut_low = (ctr < 3'd2);

  // OPEN-DRAIN: pull low, or release. Never drive high.
  assign sda = dut_low ? 1'b0 : 1'bz;

endmodule
