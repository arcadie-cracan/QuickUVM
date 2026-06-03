//----------------------------------------------------------------------
// alu_pkg — shared ALU opcode definitions.
// Named constants (enum) instead of magic numbers — used by the DUT and the
// testbench's golden model + constraint so the operation reads by name.
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
package alu_pkg;
  typedef enum logic [3:0] {
    ADD = 4'd0,
    SUB = 4'd1,
    AND = 4'd2,
    OR  = 4'd3,
    XOR = 4'd4,
    SLL = 4'd5,
    SRL = 4'd6,
    SLT = 4'd7
  } opcode_e;
endpackage
