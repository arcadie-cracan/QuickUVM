//----------------------------------------------------------------------
// axi_reorder — an AXI-read MASTER that floats a backlog with REPEATED ids, to make the
// responder's reorder_policy visible in the response order.
//
// It issues 3 reads on id 0, then 3 on id 1 (arrival id-order [0 0 0 1 1 1]); each araddr
// encodes (id, seq) so the master can check per-ID FIFO order and print the cross-id order.
// The `seq` field within an id must come back 0,1,2 (arrival order) under every policy; the
// CROSS-id interleave is what the policy chooses:
//   round_robin -> fully interleaved [0 1 0 1 0 1]  (same-id adjacency 0)  <-- this bench
//   priority    -> grouped           [0 0 0 1 1 1]  (same-id adjacency 4)
// The master checks the round-robin signature (adjacency 0) with a $fatal, so a policy
// change is caught by the regress verdict. See examples/axi_reorder/MUTATIONS.md.
//----------------------------------------------------------------------
module axi_reorder (
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
  localparam int N = 6;   // 2 ids x 3 requests; round-robin fully interleaves them -> 0
                          // same-id neighbours, which is the signature this bench checks.

  // arrival id-order: 0,0,0,1,1,1 ; araddr = {id, seq} so each request is distinct + ordered
  logic [3:0]  req_id  [N] = '{4'd0, 4'd0, 4'd0, 4'd1, 4'd1, 4'd1};
  logic [31:0] req_ad  [N] = '{32'h00, 32'h01, 32'h02, 32'h10, 32'h11, 32'h12};
  // the exact order round-robin must produce: id 0 picked alone first, then a fair 0,1,0,1,0
  // rotation as the backlog drains (see README). A weaker adjacency-only check would miss a
  // cursor regression; this pins every beat.
  logic [3:0]  exp_rr  [N] = '{4'd0, 4'd1, 4'd0, 4'd1, 4'd0, 4'd1};

  int   issued, got;
  logic [3:0]  recv_id  [N];
  logic [31:0] recv_ad  [N];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      arvalid <= 1'b0; arid <= '0; araddr <= '0; arlen <= '0;
      issued  <= 0; got <= 0;
    end else begin
      // issue all N requests, one arvalid PULSE each (distinct rising edges)
      if (issued < N && !arvalid) begin
        arvalid <= 1'b1;
        arid    <= req_id[issued];
        araddr  <= req_ad[issued];
        arlen   <= 8'd0;
        issued  <= issued + 1;
      end else begin
        arvalid <= 1'b0;
      end
      // accept R beats in whatever order the slave returns them
      if (rvalid && got < N) begin
        $display("[MASTER %0t] R beat rid=%0d rdata=0x%0h", $time, rid, rdata);
        recv_id[got] <= rid;
        recv_ad[got] <= rdata;
        got <= got + 1;
      end
    end
  end

  // End-of-test checks.
  int unsigned adj;             // same-id adjacent pairs in the receive order
  int          last_seq [16];   // per-id last seq seen (FIFO check)
  string       recv_s;
  final begin
    if (got != N)
      $error("[MASTER] got %0d of %0d R beats -- the responder STRANDED the burst.", got, N);

    // per-ID FIFO: each id's beats must arrive in issue (seq) order 0,1,2
    for (int i = 0; i < 16; i++) last_seq[i] = -1;
    for (int i = 0; i < N; i++) begin
      automatic int id  = recv_id[i];
      automatic int seq = recv_ad[i] & 32'hF;   // low nibble = seq
      if (seq <= last_seq[id])
        $fatal(1, "[MASTER] id %0d beat seq=%0d out of order (last=%0d) -- per-id FIFO broken",
               id, seq, last_seq[id]);
      last_seq[id] = seq;
    end

    // cross-id order: print it, and check it against the EXACT expected round-robin
    // sequence. Adjacency alone is too weak — [1 0 1 0 1 0] also has adjacency 0, so a
    // cursor regression (e.g. m_last_id init -1 -> 0) would pass an adjacency-only check.
    // Pinning the full sequence catches any wrong pick, not just a grouped one.
    adj = 0; recv_s = "";
    for (int i = 0; i < N; i++) begin
      recv_s = {recv_s, $sformatf("%0d ", recv_id[i])};
      if (i > 0 && recv_id[i] === recv_id[i-1]) adj++;
    end
    $display("[MASTER] recv=[ %s] got=%0d/%0d adjacency=%0d (round_robin => [ 0 1 0 1 0 1 ])",
             recv_s, got, N, adj);
    for (int i = 0; i < N; i++)
      if (recv_id[i] !== exp_rr[i])
        $fatal(1, "[MASTER] beat %0d rid=%0d, expected %0d -- not round-robin (policy changed?)",
               i, recv_id[i], exp_rr[i]);
  end
endmodule
