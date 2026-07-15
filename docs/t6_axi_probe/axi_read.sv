// A stub AXI-read MASTER (the DUT). Issues 3 outstanding read requests with distinct IDs,
// then accepts R beats in whatever order the device (TB) returns them, matching by rid.
// Records the DISPATCH ORDER and whether a cross-ID reorder occurred. This is the minimal
// shape that distinguishes an OoO responder from an in-order one.
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
  // 3 requests, issued in ID order 2, 0, 1
  localparam int N = 3;
  logic [3:0] req_id  [N] = '{4'd2, 4'd0, 4'd1};
  logic [31:0] req_ad [N] = '{32'hA0, 32'hB0, 32'hC0};

  int issued, got;
  logic [3:0] recv_order [N];         // the ID-arrival order of R beats
  bit         id_outstanding [16];    // which IDs are awaiting a response

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      arvalid <= 0; arid <= 0; araddr <= 0; arlen <= 0;
      issued <= 0; got <= 0;
      for (int i=0;i<16;i++) id_outstanding[i] <= 0;
    end else begin
      // --- issue all 3 AR requests back-to-back (one arvalid pulse each) ---
      // Pulse arvalid (drive one cycle, gap one cycle) so each AR is a DISTINCT rising
      // edge — the QuickUVM responder edge-detects the qualifier.
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
      // --- accept R beats in ANY order, record the arrival order, match by id ---
      if (rvalid && got < N) begin
        $display("[MASTER %0t] R beat rid=%0d", $time, rid);
        recv_order[got] <= rid;
        if (!id_outstanding[rid])
          $error("R beat rid=%0d has no outstanding request (bad pairing)", rid);
        id_outstanding[rid] <= 1'b0;
        got <= got + 1;
      end
    end
  end

  // end-of-test check
  int unsigned n_reorder;
  final begin
    if (got != N) $error("MASTER: got %0d R beats, expected %0d (responder backlog/deadlock?)", got, N);
    // count cross-ID reorders vs the issue order {2,0,1}
    n_reorder = 0;
    for (int i=0;i<N;i++) if (recv_order[i] !== req_id[i]) n_reorder++;
    $display("[MASTER] issue order=%0d,%0d,%0d  recv order=%0d,%0d,%0d  reorders=%0d",
             req_id[0],req_id[1],req_id[2], recv_order[0],recv_order[1],recv_order[2], n_reorder);
  end
endmodule
