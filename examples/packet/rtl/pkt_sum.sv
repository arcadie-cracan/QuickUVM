//----------------------------------------------------------------------
// pkt_sum — a tiny packet checksum DUT (QuickUVM S1 example).
//
// A variable-length packet of up to MAXB bytes is presented packed into the
// `data` bus (byte i in data[i*W +: W]); `len` says how many bytes are valid.
// The DUT sums the first `len` bytes into a 16-bit checksum. Combinational —
// one packet per vector — so the bench stays single-cycle while still
// exercising a variable-length payload.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module pkt_sum #(
    parameter int MAXB = 16,  // max bytes per packet
    parameter int W    = 8,   // byte width
    parameter int SW   = 16   // checksum width
) (
    input  logic [MAXB*W-1:0]        data,  // payload, packed low-byte-first
    input  logic [$clog2(MAXB+1)-1:0] len,  // number of valid bytes (0..MAXB)
    output logic [SW-1:0]            sum     // checksum of the first `len` bytes
);
  always_comb begin
    sum = '0;
    for (int i = 0; i < MAXB; i++) begin
      if (i < len) sum += SW'(data[i*W+:W]);
    end
  end
endmodule
