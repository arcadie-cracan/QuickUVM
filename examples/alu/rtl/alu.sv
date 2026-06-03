//----------------------------------------------------------------------
// alu — parameterized combinational ALU with Z/C/N/V flags.
// Operations are named (alu_pkg::opcode_e) rather than magic numbers.
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module alu import alu_pkg::*; #(
  parameter int W = 8
) (
  input  logic [W-1:0] a,
  input  logic [W-1:0] b,
  input  logic [3:0]   op,
  output logic [W-1:0] result,
  output logic         zero,
  output logic         carry,
  output logic         negative,
  output logic         overflow
);
  logic [W:0] add_ext, sub_ext;

  always_comb begin
    add_ext  = {1'b0, a} + {1'b0, b};
    sub_ext  = {1'b0, a} - {1'b0, b};
    carry    = 1'b0;
    overflow = 1'b0;
    unique case (opcode_e'(op))
      ADD: begin
        result   = add_ext[W-1:0];
        carry    = add_ext[W];
        overflow = (a[W-1] == b[W-1]) && (result[W-1] != a[W-1]);
      end
      SUB: begin
        result   = sub_ext[W-1:0];
        carry    = sub_ext[W];  // borrow
        overflow = (a[W-1] != b[W-1]) && (result[W-1] != a[W-1]);
      end
      AND:     result = a & b;
      OR:      result = a | b;
      XOR:     result = a ^ b;
      SLL:     result = a << b[$clog2(W)-1:0];
      SRL:     result = a >> b[$clog2(W)-1:0];
      SLT:     result = {{(W-1){1'b0}}, ($signed(a) < $signed(b))};
      default: result = '0;
    endcase
    zero     = (result == '0);
    negative = result[W-1];
  end
endmodule
