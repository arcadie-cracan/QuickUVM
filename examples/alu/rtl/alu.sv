//----------------------------------------------------------------------
// alu — parameterized combinational ALU with Z/C/N/V flags.
// op: 0 ADD, 1 SUB, 2 AND, 3 OR, 4 XOR, 5 SLL, 6 SRL, 7 SLT (signed).
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module alu #(
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
    unique case (op)
      4'd0: begin  // ADD
        result   = add_ext[W-1:0];
        carry    = add_ext[W];
        overflow = (a[W-1] == b[W-1]) && (result[W-1] != a[W-1]);
      end
      4'd1: begin  // SUB
        result   = sub_ext[W-1:0];
        carry    = sub_ext[W];  // borrow
        overflow = (a[W-1] != b[W-1]) && (result[W-1] != a[W-1]);
      end
      4'd2:    result = a & b;                                          // AND
      4'd3:    result = a | b;                                          // OR
      4'd4:    result = a ^ b;                                          // XOR
      4'd5:    result = a << b[$clog2(W)-1:0];                          // SLL
      4'd6:    result = a >> b[$clog2(W)-1:0];                          // SRL
      4'd7:    result = {{(W-1){1'b0}}, ($signed(a) < $signed(b))};     // SLT
      default: result = '0;
    endcase
    zero     = (result == '0);
    negative = result[W-1];
  end
endmodule
