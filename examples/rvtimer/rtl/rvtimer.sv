//----------------------------------------------------------------------
// rvtimer — an rv_timer-equivalent timer block behind a minimal single-cycle
// register bus (QuickUVM maturity-assessment DUT; see docs/maturity_assessment_
// rv_timer.md). Deliberately generic (no TileLink) so the comparison isolates the
// DV *generation*, not the bus protocol.
//
// Registers (16-bit, byte offsets; idx = addr[3:1]):
//   0x0 CTRL         [0] enable
//   0x2 CFG          [7:0] step (mtime increment per enabled cycle)
//   0x4 MTIMECMP     16-bit compare value
//   0x6 INTR_ENABLE  [0] interrupt enable
//   0x8 INTR_STATE   [0] RO interrupt pending (set by hw when mtime >= mtimecmp)
//
// When enabled, `mtime` increments by `step` each cycle; on reaching MTIMECMP the
// interrupt-pending state sets and, if INTR_ENABLE[0], the `intr` output asserts.
// Disabling (CTRL[0]=0) resets the counter and clears the pending state — so the
// interrupt is armed/cleared purely through CTRL, and stays quiet during the CSR
// tests (which leave CTRL at its 0 reset except transiently, with MTIMECMP=0xFFFF).
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module rvtimer #(
    parameter int AW = 5,
    parameter int DW = 16
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic [AW-1:0] addr,
    input  logic [DW-1:0] wdata,
    input  logic          wr,
    output logic [DW-1:0] rdata,
    output logic          intr
);
  wire [2:0] idx = addr[3:1];  // 16-bit regs at byte offsets 0/2/4/6/8

  logic [15:0] ctrl;
  logic [15:0] cfg;
  logic [15:0] mtimecmp;
  logic [15:0] inten;
  logic [15:0] mtime;
  logic        intr_state;

  wire        enable = ctrl[0];
  wire [7:0]  step   = cfg[7:0];

  // --- register writes (INTR_STATE at idx 4 is read-only) ---
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ctrl     <= 16'h0000;
      cfg      <= 16'h0001;  // step = 1
      mtimecmp <= 16'hFFFF;  // large: no interrupt during the CSR tests
      inten    <= 16'h0000;
    end else if (wr) begin
      case (idx)
        3'd0: ctrl     <= wdata;
        3'd1: cfg      <= wdata;
        3'd2: mtimecmp <= wdata;
        3'd3: inten    <= wdata;
        default: ;  // 3'd4 INTR_STATE is RO
      endcase
    end
  end

  // --- timer + interrupt-pending state ---
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      mtime      <= 16'h0000;
      intr_state <= 1'b0;
    end else if (!enable) begin
      mtime      <= 16'h0000;  // disabled: reset counter and clear pending
      intr_state <= 1'b0;
    end else begin
      mtime <= mtime + {8'h00, step};
      if ((mtime + {8'h00, step}) >= mtimecmp) intr_state <= 1'b1;
    end
  end

  assign intr = intr_state & inten[0];

  // --- combinational read ---
  always_comb begin
    case (idx)
      3'd0:    rdata = ctrl;
      3'd1:    rdata = cfg;
      3'd2:    rdata = mtimecmp;
      3'd3:    rdata = inten;
      3'd4:    rdata = {15'h0000, intr_state};
      default: rdata = 16'h0000;
    endcase
  end
endmodule
