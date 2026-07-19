//----------------------------------------------------------------------
// axi_write — a stub AXI-write MASTER (the DUT under a pipelined write responder).
// The FIRST slice of the AXI 5-channel VIP epic: the WRITE side (AW + W -> B), the
// counterpart to examples/axi_read's read side (AR -> R). See docs/axi_epic_assessment.md.
//
// The write channel's NEW challenge vs the read: TWO request channels (the write ADDRESS
// AW and the write DATA W) must be correlated into ONE response (B). AXI4 rule: W beats
// follow AW beats IN ORDER (W has no id). So the slave pairs the k-th W burst with the
// k-th AW. Here the testbench does that correlation in its monitor (an awid queue popped
// on WLAST), then answers B OUT OF ORDER by bid via `respond: pipelined`.
//
// This DUT floats N writes with DISTINCT descending ids: all AW beats first, then all W
// beats (single-beat, WLAST each). It accepts B beats in whatever order the slave returns
// them, matches each to an outstanding write by bid, and checks that a cross-id REORDER
// occurred (a lowest-id-first slave drains the descending backlog in ascending order).
//----------------------------------------------------------------------
module axi_write (
  input  logic        clk,
  input  logic        rst_n,
  // AW channel — the DUT drives, the TB samples
  output logic        awvalid,
  output logic [3:0]  awid,
  output logic [31:0] awaddr,
  // W channel — the DUT drives, the TB samples
  output logic        wvalid,
  output logic [31:0] wdata,
  output logic        wlast,
  // B channel — the TB drives, the DUT samples
  input  logic        bvalid,
  input  logic [3:0]  bid,
  input  logic [1:0]  bresp
);
  localparam int N = 5;
  logic [3:0]  wr_id [N] = '{4'd4, 4'd3, 4'd2, 4'd1, 4'd0};
  logic [31:0] wr_ad [N] = '{32'h40, 32'h30, 32'h20, 32'h10, 32'h00};

  int aw_sent, w_sent, got;
  logic [3:0] recv_order [N];
  bit         id_outstanding [16];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      awvalid <= 1'b0; awid <= '0; awaddr <= '0;
      wvalid  <= 1'b0; wdata <= '0; wlast <= 1'b0;
      aw_sent <= 0; w_sent <= 0; got <= 0;
      for (int i = 0; i < 16; i++) id_outstanding[i] <= 1'b0;
    end else begin
      // Phase 1: float every AW (distinct id), one PULSE each (a distinct rising edge).
      if (aw_sent < N && !awvalid) begin
        awvalid <= 1'b1;
        awid    <= wr_id[aw_sent];
        awaddr  <= wr_ad[aw_sent];
        id_outstanding[wr_id[aw_sent]] <= 1'b1;
        aw_sent <= aw_sent + 1;
      end else begin
        awvalid <= 1'b0;
      end
      // Phase 2: after all AW, float the W data IN THE SAME ORDER (single-beat, WLAST).
      // W has no id — the slave pairs each W with the matching AW by order. To make that ORDER
      // observable, each W beat carries a self-describing tag: the low nibble of wdata is the id
      // of the AW it belongs to. A slave that pairs it with the WRONG AW sees tag != awid.
      if (aw_sent == N && w_sent < N && !wvalid) begin
        wvalid <= 1'b1;
        wdata  <= {wr_ad[w_sent][27:0], wr_id[w_sent]};  // payload || id-tag in wdata[3:0]
        wlast  <= 1'b1;                                   // single-beat: every W is the last
        w_sent <= w_sent + 1;
      end else begin
        wvalid <= 1'b0;
        wlast  <= 1'b0;
      end
      // Accept B beats in ANY order; record arrival order; match by bid; check the response.
      if (bvalid && got < N) begin
        $display("[WMASTER %0t] B beat bid=%0d bresp=%0d", $time, bid, bresp);
        recv_order[got] <= bid;
        if (!id_outstanding[bid])
          $error("[WMASTER] B beat bid=%0d has no outstanding write (bad pairing)", bid);
        // SLVERR means the slave found wdata's id-tag did not match the AW it was paired with —
        // i.e. the AW/W ORDER correlation was wrong. bresp makes wrong-ORDER visible end-to-end.
        if (bresp !== 2'b00)
          $error("[WMASTER] B beat bid=%0d SLVERR — the slave saw a mis-ORDERED AW/W pairing", bid);
        id_outstanding[bid] <= 1'b0;
        got <= got + 1;
      end
    end
  end

  int unsigned n_reorder;
  string       issue_s, recv_s;
  final begin
    n_reorder = 0; issue_s = ""; recv_s = "";
    for (int i = 0; i < N; i++) begin
      if (recv_order[i] !== wr_id[i]) n_reorder++;
      issue_s = {issue_s, $sformatf("%0d ", wr_id[i])};
      recv_s  = {recv_s,  $sformatf("%0d ", recv_order[i])};
    end
    $display("[WMASTER] issue = [ %s]  B recv = [ %s]  got=%0d/%0d  cross-id reorders=%0d",
             issue_s, recv_s, got, N, n_reorder);
    if (got != N)
      $error("[WMASTER] got %0d of %0d B beats — the responder STRANDED writes.", got, N);
    else if (n_reorder == 0)
      $error("[WMASTER] all %0d B beats arrived in ISSUE order — no cross-id reorder.", N);
  end
endmodule
