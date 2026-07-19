//----------------------------------------------------------------------
// axi_slave — a stub AXI MASTER exercising BOTH channels at once (the AXI epic, slice 4).
//
// The capstone: a full AXI slave is not a new agent shape, it is the COMPOSITION of a read
// agent (AR -> R) and a write agent (AW + W -> B) on one DUT — the decomposition T6 named
// (docs/t6_axi_outstanding_assessment.md §4). This DUT is the master that drives both; the
// testbench answers with two INDEPENDENT responder agents, each reusing a prior slice:
//   * reads  -> examples/axi_read  (pipelined, out-of-order by arid)
//   * writes -> examples/axi_write (the AW/W order-correlation, out-of-order by bid)
//
// It floats N=3 reads and N=3 writes with DISTINCT descending ids, accepts R and B beats in
// whatever order the two slaves return them (each drains lowest-id-first, so a descending
// backlog comes back reordered), matches each by id, and checks it received them all.
//----------------------------------------------------------------------
module axi_slave (
  input  logic        clk,
  input  logic        rst_n,
  // READ address (master drives) + read data (slave drives)
  output logic        arvalid,
  output logic [3:0]  arid,
  output logic [31:0] araddr,
  input  logic        rvalid,
  input  logic [3:0]  rid,
  input  logic [31:0] rdata,
  input  logic        rlast,
  // WRITE address + write data (master drives) + write response (slave drives)
  output logic        awvalid,
  output logic [3:0]  awid,
  output logic [31:0] awaddr,
  output logic        wvalid,
  output logic [31:0] wdata,
  output logic        wlast,
  input  logic        bvalid,
  input  logic [3:0]  bid,
  input  logic [1:0]  bresp
);
  localparam int N = 3;
  logic [3:0]  r_id [N] = '{4'd3, 4'd2, 4'd1};
  logic [31:0] r_ad [N] = '{32'h30, 32'h20, 32'h10};
  logic [3:0]  w_id [N] = '{4'd3, 4'd2, 4'd1};
  logic [31:0] w_ad [N] = '{32'hC0, 32'hB0, 32'hA0};

  // ---- READ channel ----
  int  ar_sent, r_got;
  bit  r_out [16];
  logic [3:0] r_recv [N];
  // ---- WRITE channel ----
  int  aw_sent, w_sent, b_got;
  bit  b_out [16];
  logic [3:0] b_recv [N];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      arvalid <= 1'b0; arid <= '0; araddr <= '0;
      awvalid <= 1'b0; awid <= '0; awaddr <= '0;
      wvalid  <= 1'b0; wdata <= '0; wlast <= 1'b0;
      ar_sent <= 0; r_got <= 0; aw_sent <= 0; w_sent <= 0; b_got <= 0;
      for (int i = 0; i < 16; i++) begin r_out[i] <= 1'b0; b_out[i] <= 1'b0; end
    end else begin
      // READ: float each AR as a distinct pulse.
      if (ar_sent < N && !arvalid) begin
        arvalid <= 1'b1; arid <= r_id[ar_sent]; araddr <= r_ad[ar_sent];
        r_out[r_id[ar_sent]] <= 1'b1; ar_sent <= ar_sent + 1;
      end else arvalid <= 1'b0;
      if (rvalid && r_got < N) begin
        r_recv[r_got] <= rid;
        if (!r_out[rid]) $error("[SLAVE] R beat rid=%0d not outstanding", rid);
        r_out[rid] <= 1'b0; r_got <= r_got + 1;
      end

      // WRITE: float all AW (distinct pulses), then all W in the same order (id-tagged data).
      if (aw_sent < N && !awvalid) begin
        awvalid <= 1'b1; awid <= w_id[aw_sent]; awaddr <= w_ad[aw_sent];
        b_out[w_id[aw_sent]] <= 1'b1; aw_sent <= aw_sent + 1;
      end else awvalid <= 1'b0;
      if (aw_sent == N && w_sent < N && !wvalid) begin
        wvalid <= 1'b1; wdata <= {w_ad[w_sent][27:0], w_id[w_sent]}; wlast <= 1'b1;
        w_sent <= w_sent + 1;
      end else begin wvalid <= 1'b0; wlast <= 1'b0; end
      if (bvalid && b_got < N) begin
        b_recv[b_got] <= bid;
        if (!b_out[bid]) $error("[SLAVE] B beat bid=%0d not outstanding", bid);
        if (bresp !== 2'b00) $error("[SLAVE] B beat bid=%0d SLVERR (mis-ordered AW/W)", bid);
        b_out[bid] <= 1'b0; b_got <= b_got + 1;
      end
    end
  end

  int unsigned r_reorder, b_reorder;
  final begin
    r_reorder = 0; b_reorder = 0;
    for (int i = 0; i < N; i++) begin
      if (r_recv[i] !== r_id[i]) r_reorder++;
      if (b_recv[i] !== w_id[i]) b_reorder++;
    end
    $display("[SLAVE] reads got=%0d/%0d reorders=%0d | writes got=%0d/%0d reorders=%0d",
             r_got, N, r_reorder, b_got, N, b_reorder);
    if (r_got != N) $error("[SLAVE] read channel stranded (%0d/%0d)", r_got, N);
    if (b_got != N) $error("[SLAVE] write channel stranded (%0d/%0d)", b_got, N);
  end
endmodule
