//----------------------------------------------------------------------
// regfile — a tiny register file behind a minimal single-cycle bus
// (QuickUVM C5 / RAL example DUT).
//
// Four 16-bit R/W registers at byte offsets 0/2/4/6 with distinct reset values
// (so the hw_reset CSR test has something to check). One access per cycle: when
// `wr`, write `wdata` to the addressed register; `rdata` is the addressed
// register (combinational read).
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module regfile #(
    parameter int AW = 4,
    parameter int DW = 16
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic [AW-1:0] addr,
    input  logic [DW-1:0] wdata,
    input  logic          wr,
    output logic [DW-1:0] rdata
);
  // byte offset -> register index (16-bit regs at 0/2/4/6)
  wire [1:0] idx = addr[2:1];
  logic [DW-1:0] regs[4];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      regs[0] <= 16'h0000;  // ctrl
      regs[1] <= 16'h00FF;  // cfg
      regs[2] <= 16'hDEAD;  // scratch
      regs[3] <= 16'hBEEF;  // status
    end else if (wr) begin
      regs[idx] <= wdata;
    end
  end

  assign rdata = regs[idx];
endmodule
