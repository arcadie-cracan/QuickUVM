//----------------------------------------------------------------------
// axi_read — a stub AXI-read MASTER (the DUT under a pipelined responder).
//
// It floats N read requests (AR beats) with DISTINCT ids BEFORE any is answered, then
// accepts R beats in whatever order the slave (the testbench) returns them, matching each
// to its outstanding request by `rid`. It records the arrival order and, at end of test,
// reports how many beats it got and whether a cross-ID REORDER occurred.
//
// This is the minimal DUT that distinguishes a multi-outstanding out-of-order slave from an
// in-order (or stranding) one: an in-order slave returns rids in issue order; a stranding
// slave never returns them all. See docs/t6_axi_outstanding_assessment.md.
//----------------------------------------------------------------------
module axi_read (
  input  logic        clk,
  input  logic        rst_n,
  output logic        arvalid,
  output logic [3:0]  arid,
  output logic [31:0] araddr,
  output logic [7:0]  arlen,
  input  logic        rvalid,
  input  logic [3:0]  rid,
  input  logic [31:0] rdata,
  input  logic        rlast
);
  // Five requests, floated in DESCENDING id order 4,3,2,1,0. The slave models a read
  // latency, so a backlog accumulates; its lowest-ready-id-first policy then drains it in
  // ASCENDING id order — a visible, deterministic cross-ID reorder (recv != issue).
  localparam int N = 5;
  logic [3:0]  req_id [N] = '{4'd4, 4'd3, 4'd2, 4'd1, 4'd0};
  logic [31:0] req_ad [N] = '{32'h40, 32'h30, 32'h20, 32'h10, 32'h00};

  int   issued, got;
  logic [3:0] recv_order [N];       // the id-arrival order of the R beats
  bit         id_outstanding [16];  // which ids are awaiting a response

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      arvalid <= 1'b0; arid <= '0; araddr <= '0; arlen <= '0;
      issued  <= 0; got <= 0;
      for (int i = 0; i < 16; i++) id_outstanding[i] <= 1'b0;
    end else begin
      // --- issue all N AR requests back-to-back, one arvalid PULSE each ---
      // Pulse (drive one cycle, release the next) so every AR is a DISTINCT rising edge:
      // the responder's monitor edge-detects the qualifier. Holding arvalid high would be
      // one request, not N.
      if (issued < N && !arvalid) begin
        arvalid <= 1'b1;
        arid    <= req_id[issued];
        araddr  <= req_ad[issued];
        arlen   <= 8'd0;
        id_outstanding[req_id[issued]] <= 1'b1;
        issued  <= issued + 1;
      end else begin
        arvalid <= 1'b0;
      end
      // --- accept R beats in ANY order; record arrival order; match by id ---
      if (rvalid && got < N) begin
        $display("[MASTER %0t] R beat rid=%0d rdata=0x%0h", $time, rid, rdata);
        recv_order[got] <= rid;
        if (!id_outstanding[rid])
          $error("[MASTER] R beat rid=%0d has no outstanding request (bad pairing)", rid);
        id_outstanding[rid] <= 1'b0;
        got <= got + 1;
      end
    end
  end

  // End-of-test report. The UVM verdict is carried by the responder's STRANDED_REQUESTS /
  // DEAD_RESPONDER checks; this is human-readable corroboration of the same facts.
  int unsigned n_reorder;
  string       issue_s, recv_s;
  final begin
    n_reorder = 0;
    issue_s = ""; recv_s = "";
    for (int i = 0; i < N; i++) begin
      if (recv_order[i] !== req_id[i]) n_reorder++;
      issue_s = {issue_s, $sformatf("%0d ", req_id[i])};
      recv_s  = {recv_s,  $sformatf("%0d ", recv_order[i])};
    end
    $display("[MASTER] issue order = [ %s]  recv order = [ %s]  got=%0d/%0d  cross-id reorders=%0d",
             issue_s, recv_s, got, N, n_reorder);
    if (got != N)
      $error("[MASTER] got %0d of %0d R beats — the responder STRANDED the burst.", got, N);
    else if (n_reorder == 0)
      $error("[MASTER] all %0d beats arrived in ISSUE order — no cross-id reorder occurred.", N);
  end
endmodule
