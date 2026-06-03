//----------------------------------------------------------------------
// barrel_shifter — parameterized combinational barrel shifter
// Modes: SLL, SRL, SRA, ROL, ROR. Purely combinational (no clock/reset).
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module barrel_shifter #(
  parameter int W = 32
) (
  input  logic [W-1:0]          data_in,
  input  logic [$clog2(W)-1:0]  amt,
  input  logic [2:0]            op,        // 0:SLL 1:SRL 2:SRA 3:ROL 4:ROR
  output logic [W-1:0]          data_out
);
  localparam logic [2:0] SLL = 3'd0, SRL = 3'd1, SRA = 3'd2, ROL = 3'd3, ROR = 3'd4;

  always_comb begin
    unique case (op)
      SLL:     data_out = data_in << amt;
      SRL:     data_out = data_in >> amt;
      SRA:     data_out = $signed(data_in) >>> amt;
      ROL:     data_out = (amt == '0) ? data_in : (data_in << amt) | (data_in >> (W - amt));
      ROR:     data_out = (amt == '0) ? data_in : (data_in >> amt) | (data_in << (W - amt));
      default: data_out = data_in;
    endcase
  end
endmodule
