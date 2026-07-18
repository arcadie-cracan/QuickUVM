//----------------------------------------------------------------------
// cdc_fifo — a dual-clock (asynchronous) FIFO: data pushed in the WRITE clock domain
// crosses to the READ clock domain via gray-coded pointers + 2-flop synchronizers
// (the classic Cliff Cummings design). The two domains run on unrelated clocks, so a
// scoreboard checking data-in == data-out must match a WRITE-domain stream against a
// READ-domain stream across the crossing — the cross-domain-integrity check.
//
// A FIFO preserves ORDER: the Nth word pushed is the Nth word popped, with a variable,
// bounded latency (synchronizer depth + occupancy). `wxfer`/`rxfer` mark a real
// push/pop so the testbench qualifies exactly the transferred words.
//
// `wfull` (hence `wready`) is REGISTERED, per Cummings: computing it combinationally from
// the NEXT write pointer would form a loop `wxfer -> wbin_nxt -> wgray_nxt -> wready ->
// wxfer` and hang the simulation in delta cycles. `rempty` is safe combinationally
// because it reads the current (registered) read pointer, not the next.
//----------------------------------------------------------------------
module cdc_fifo #(
  parameter int DW = 8,
  parameter int AW = 3          // depth = 2**AW
) (
  // write domain
  input  logic          wclk,
  input  logic          wrst_n,
  input  logic          wvalid,   // the master wants to push
  input  logic [DW-1:0] wdata,
  output logic          wready,   // FIFO not full
  output logic          wxfer,    // a push actually happened this cycle
  // read domain
  input  logic          rclk,
  input  logic          rrst_n,
  input  logic          rready,   // the master wants to pop
  output logic [DW-1:0] rdata,    // head word (valid when rvalid)
  output logic          rvalid,   // FIFO not empty
  output logic          rxfer     // a pop actually happened this cycle
);
  localparam int DEPTH = 1 << AW;
  logic [DW-1:0] mem [DEPTH];

  logic [AW:0] wbin, wgray, rbin, rgray;
  logic [AW:0] wbin_nxt, wgray_nxt, rbin_nxt, rgray_nxt;
  logic [AW:0] wgray_s1, wgray_s2;   // write gray synced into the read domain
  logic [AW:0] rgray_s1, rgray_s2;   // read  gray synced into the write domain
  logic        wfull;                // REGISTERED — breaks the combinational loop

  // ---- write domain -------------------------------------------------
  assign wready    = !wfull;
  assign wxfer     = wvalid && !wfull;   // !wfull is a reg output -> no comb loop
  assign wbin_nxt  = wbin + (wxfer ? 1 : 0);
  assign wgray_nxt = (wbin_nxt >> 1) ^ wbin_nxt;
  always_ff @(posedge wclk or negedge wrst_n) begin
    if (!wrst_n) begin
      wbin <= '0; wgray <= '0; wfull <= 1'b0;
    end else begin
      if (wxfer) mem[wbin[AW-1:0]] <= wdata;
      wbin  <= wbin_nxt;
      wgray <= wgray_nxt;
      // full when the NEXT write gray equals the synced read gray with the top two bits
      // inverted (Cummings). Registered, so it lags one cycle — which is why the write
      // enable above gates on the registered value.
      wfull <= (wgray_nxt == {~rgray_s2[AW:AW-1], rgray_s2[AW-2:0]});
    end
  end
  always_ff @(posedge wclk or negedge wrst_n)
    if (!wrst_n) {rgray_s2, rgray_s1} <= '0;
    else         {rgray_s2, rgray_s1} <= {rgray_s1, rgray};

  // ---- read domain --------------------------------------------------
  assign rxfer     = rready && rvalid;
  assign rbin_nxt  = rbin + (rxfer ? 1 : 0);
  assign rgray_nxt = (rbin_nxt >> 1) ^ rbin_nxt;
  always_ff @(posedge rclk or negedge rrst_n) begin
    if (!rrst_n) begin
      rbin <= '0; rgray <= '0;
    end else begin
      rbin  <= rbin_nxt;
      rgray <= rgray_nxt;
    end
  end
  always_ff @(posedge rclk or negedge rrst_n)
    if (!rrst_n) {wgray_s2, wgray_s1} <= '0;
    else         {wgray_s2, wgray_s1} <= {wgray_s1, wgray};
  assign rvalid = (rgray != wgray_s2);          // not empty (from the REGISTERED read gray)
  assign rdata  = mem[rbin[AW-1:0]];            // head word (first-word-fall-through)
endmodule
