//----------------------------------------------------------------------
// gated_add — rand_mode demo DUT (QuickUVM S1 example).
//
// Trivial combinational adder y = a + bias. The point is the bench: `bias` is a
// `rand` field whose randomization is DISABLED by default (rand_mode(0)), so it
// holds 0 and y == a — until a sequence re-enables it with bias.rand_mode(1).
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module gated_add #(
    parameter int W = 8
) (
    input  logic [W-1:0] a,
    input  logic [W-1:0] bias,
    output logic [W:0]   y
);
  assign y = a + bias;
endmodule
