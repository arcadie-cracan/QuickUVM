//----------------------------------------------------------------------
// ahb_regs — a minimal AHB-Lite register slave with a REGISTERED read path.
//
// AHB-Lite splits every access into an ADDRESS phase and a DATA phase one cycle later:
//   cycle N   : the master drives HADDR / HWRITE / HTRANS (address phase)
//   cycle N+1 : HRDATA is valid (read) or HWDATA is captured (write) — the DATA phase
// The read here is REGISTERED (HRDATA <= regs[addr] on the clock), so HRDATA in cycle
// N+1 reflects the address sampled in cycle N, and the address is only valid for that one
// address-phase cycle. A testbench that samples HRDATA in the SAME cycle it drives HADDR
// reads the PREVIOUS access's data — the stale-read gap this bench exists to expose.
//
// HREADY is tied high (no wait states) to keep the protocol minimal; HRESP is OKAY.
//----------------------------------------------------------------------
module ahb_regs #(
  parameter int AW = 12,
  parameter int DW = 32
) (
  input  logic          HCLK,
  input  logic          HRESETn,
  input  logic [AW-1:0] HADDR,
  input  logic          HWRITE,
  input  logic [1:0]    HTRANS,   // 2'b00 IDLE, 2'b10 NONSEQ, 2'b11 SEQ
  input  logic [DW-1:0] HWDATA,
  output logic [DW-1:0] HRDATA,
  output logic          HREADY,
  output logic          HRESP
);
  localparam int N = 4;                       // ctrl, cfg, scratch, status
  logic [DW-1:0] regs [N];

  // address-phase capture (registered so the write/read lands in the data phase)
  logic [1:0]    idx_q;
  logic          wr_q, active_q;

  assign HREADY = 1'b1;
  assign HRESP  = 1'b0;

  function automatic logic [1:0] idx(logic [AW-1:0] a);
    return a[3:2];                            // word address -> one of 4 registers
  endfunction

  always_ff @(posedge HCLK or negedge HRESETn) begin
    if (!HRESETn) begin
      idx_q <= '0; wr_q <= 1'b0; active_q <= 1'b0;
      regs[0] <= 32'h0000_0000;   // ctrl    (reset 0)
      regs[1] <= 32'h0000_00FF;   // cfg
      regs[2] <= 32'hDEAD_BEEF;   // scratch
      regs[3] <= 32'hCAFE_0000;   // status
      HRDATA  <= '0;
    end else begin
      // latch the address phase
      active_q <= HTRANS[1];                  // NONSEQ or SEQ = a real transfer
      wr_q     <= HWRITE;
      idx_q    <= idx(HADDR);
      // DATA phase (one cycle after the address phase): a write commits here.
      if (active_q && wr_q) regs[idx_q] <= HWDATA;
      // REGISTERED read: select on the ADDRESS-phase HADDR, register the output, so HRDATA
      // is valid the DATA phase (one cycle after the address) — the AHB read pipeline.
      HRDATA   <= regs[idx(HADDR)];
    end
  end
endmodule
