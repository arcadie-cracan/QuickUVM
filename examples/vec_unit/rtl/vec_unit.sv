//----------------------------------------------------------------------
// vec_unit — packed-struct + packed-array demo DUT (QuickUVM S1 example).
//
// `hdr` is a packed header {tag[W-1:0], en} (en in bit 0, tag in the high bits,
// matching a SystemVerilog `struct packed { bit[W-1:0] tag; bit en; }`). `lanes`
// is a packed array of NL bytes (lane i = lanes[i*W +: W]). When enabled, `sum`
// is the sum of the lanes; `tag_out` echoes the header tag. Combinational — one
// vector per transaction.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module vec_unit #(
    parameter int NL = 4,  // number of lanes
    parameter int W  = 8   // lane / tag width
) (
    input  logic [NL*W-1:0]            lanes,
    input  logic [W:0]                 hdr,      // {tag[W-1:0], en}
    output logic [W+$clog2(NL)-1:0]    sum,
    output logic [W-1:0]               tag_out
);
  logic         en;
  logic [W-1:0] tag;
  assign en  = hdr[0];
  assign tag = hdr[W:1];

  always_comb begin
    sum = '0;
    if (en) begin
      for (int i = 0; i < NL; i++) sum += lanes[i*W+:W];
    end
  end

  assign tag_out = tag;
endmodule
