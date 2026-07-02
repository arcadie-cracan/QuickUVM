//----------------------------------------------------------------------
// pwidth — a width-parameterized combinational DUT (QuickUVM C3 example).
//
// dout = din + 1, at a parameterized width W. The point is the PARAMETERIZED
// agent VIP: the interface and all UVM classes are #(W), so the same VIP is
// reusable at any width.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module pwidth #(
    parameter int W = 8
) (
    input  logic [W-1:0] din,
    output logic [W-1:0] dout
);
  assign dout = din + 1'b1;
endmodule
