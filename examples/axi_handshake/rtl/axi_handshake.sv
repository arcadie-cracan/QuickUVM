//----------------------------------------------------------------------
// axi_handshake — a stub AXI-read MASTER exercising the valid/ready HANDSHAKE (epic slice 3).
//
// Unlike the earlier valid-only examples, this master HOLDS arvalid and transfers a request only
// on arvalid && arready — and it presents its N requests BACK-TO-BACK (a new arid every cycle the
// slave accepts). That is the case examples/axi_read could not: an edge-detect monitor would see
// only the FIRST of a held-valid burst (docs/t6_axi_outstanding_assessment.md §4). The `request_ready`
// feature makes the monitor capture on the handshake (level, one per accepted cycle) instead.
//
// The RESPONSE side has backpressure too: the master drives rready LOW every third cycle, so the
// slave must HOLD rvalid until rready (the R-channel handshake). The master matches each R beat to
// an outstanding request by rid and checks it received them all.
//----------------------------------------------------------------------
module axi_handshake (
  input  logic        clk,
  input  logic        rst_n,
  // AR channel: master holds arvalid + payload; slave drives arready
  output logic        arvalid,
  output logic [3:0]  arid,
  output logic [31:0] araddr,
  input  logic        arready,
  // R channel: slave holds rvalid + payload until rready; master drives rready
  input  logic        rvalid,
  input  logic [3:0]  rid,
  input  logic [31:0] rdata,
  output logic        rready
);
  localparam int N = 4;
  logic [3:0]  req_id [N] = '{4'd1, 4'd2, 4'd3, 4'd4};
  logic [31:0] req_ad [N] = '{32'h10, 32'h20, 32'h30, 32'h40};

  int         sent;   // AR transfers accepted (arvalid && arready)
  int         got;    // R transfers accepted (rvalid && rready)
  bit         id_out [16];
  logic [1:0] rr_cnt; // rready backpressure counter

  // AR outputs are combinational from `sent`: arvalid HELD while requests remain, a new arid
  // each cycle the previous one is accepted (back-to-back under a held valid).
  assign arvalid = (sent < N);
  assign arid    = (sent < N) ? req_id[sent] : 4'd0;
  assign araddr  = (sent < N) ? req_ad[sent] : 32'd0;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rready <= 1'b0; sent <= 0; got <= 0; rr_cnt <= 0;
      for (int i = 0; i < 16; i++) id_out[i] <= 1'b0;
    end else begin
      // AR handshake: on an accepted transfer, record the id and advance to the next request.
      if (arvalid && arready) begin
        $display("[HS %0t] AR accept #%0d arid=%0d", $time, sent, arid);
        id_out[arid] <= 1'b1;
        sent <= sent + 1;
      end
      // rready backpressure: high 2 of every 3 cycles (low when the counter wraps).
      rr_cnt <= (rr_cnt == 2'd2) ? 2'd0 : rr_cnt + 2'd1;
      rready <= (rr_cnt != 2'd2);
      // R handshake: accept a beat only when rvalid && rready.
      if (rvalid && rready && got < N) begin
        $display("[HS %0t] R  accept #%0d rid=%0d rdata=0x%0h", $time, got, rid, rdata);
        if (!id_out[rid])
          $error("[HS] R beat rid=%0d has no outstanding request", rid);
        id_out[rid] <= 1'b0;
        got <= got + 1;
      end
    end
  end

  final begin
    $display("[HS MASTER] AR accepted=%0d/%0d  R accepted=%0d/%0d", sent, N, got, N);
    if (sent != N)
      $error("[HS MASTER] only %0d of %0d AR transfers accepted", sent, N);
    if (got != N)
      $error("[HS MASTER] only %0d of %0d R beats received — requests were lost/stranded", got, N);
  end
endmodule
