//----------------------------------------------------------------------
// vip — a trivial combinational DUT (QuickUVM F2 packaged-layout example).
//
// The logic is incidental (dout = din + 1); the point of this example is the
// PACKAGED testbench layout: a standalone io_pkg agent VIP, a vip_env_pkg, and a
// vip_test_pkg, each with its own .f filelist.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module vip #(
    parameter int W = 8
) (
    input  logic [W-1:0] din,
    output logic [W-1:0] dout
);
  assign dout = din + 8'd1;
endmodule
