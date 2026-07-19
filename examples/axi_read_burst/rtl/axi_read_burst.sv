//----------------------------------------------------------------------
// axi_read_burst — a stub AXI-read MASTER that issues BURST reads (the AXI epic, slice 2).
//
// The read channel again (AR -> R), but each read is a BURST: one AR carries a length ARLEN,
// and the slave answers with ARLEN+1 R data beats, RLAST asserted on the last. This is the new
// capability the single-beat examples/axi_read did not exercise: the responder must DRIVE a
// multi-beat burst (not one beat, RLAST always 1). See docs/axi_epic_assessment.md.
//
// To isolate BURSTS from out-of-order (that is axi_read's axis), this master issues one read at
// a time and waits for the whole burst before the next. It checks, per beat: rid matches the
// request, RLAST is high IFF this is the last beat (beat == ARLEN), and the data follows the
// slave's memory model rdata == araddr + beat_index. Bursts of different lengths (1,4,2,3
// beats) exercise ARLEN = 0 and ARLEN > 0.
//----------------------------------------------------------------------
module axi_read_burst (
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
  localparam int M = 4;
  logic [3:0]  rd_id  [M] = '{4'd1, 4'd2, 4'd3, 4'd4};
  logic [31:0] rd_ad  [M] = '{32'h100, 32'h200, 32'h300, 32'h400};
  logic [7:0]  rd_len [M] = '{8'd0, 8'd3, 8'd1, 8'd2};   // ARLEN: 1,4,2,3 beats

  int  ridx;       // which read
  int  beat;       // beats seen in the current burst
  bit  ar_done;    // AR issued for the current read (awaiting its data)
  int  total_beats, total_expected;

  initial begin
    total_expected = 0;
    for (int i = 0; i < M; i++) total_expected += (rd_len[i] + 1);
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      arvalid <= 1'b0; arid <= '0; araddr <= '0; arlen <= '0;
      ridx <= 0; beat <= 0; ar_done <= 1'b0; total_beats <= 0;
    end else begin
      // Issue the AR for the current read (one pulse), then wait for its whole burst.
      if (ridx < M && !ar_done && !arvalid) begin
        arvalid <= 1'b1;
        arid    <= rd_id[ridx];
        araddr  <= rd_ad[ridx];
        arlen   <= rd_len[ridx];
        ar_done <= 1'b1;
      end else begin
        arvalid <= 1'b0;
      end
      // Collect the R beats of the current burst; check framing + data.
      if (rvalid && ridx < M) begin
        $display("[BURST %0t] read %0d beat %0d: rid=%0d rdata=0x%0h rlast=%0b",
                 $time, ridx, beat, rid, rdata, rlast);
        if (rid !== rd_id[ridx])
          $error("[BURST] read %0d beat %0d: rid=%0d expected %0d", ridx, beat, rid, rd_id[ridx]);
        if (rdata !== rd_ad[ridx] + beat)
          $error("[BURST] read %0d beat %0d: rdata=0x%0h expected 0x%0h",
                 ridx, beat, rdata, rd_ad[ridx] + beat);
        if (rlast !== (beat == int'(rd_len[ridx])))
          $error("[BURST] read %0d beat %0d: rlast=%0b expected %0b",
                 ridx, beat, rlast, (beat == int'(rd_len[ridx])));
        total_beats <= total_beats + 1;
        if (rlast) begin
          ridx    <= ridx + 1;
          beat    <= 0;
          ar_done <= 1'b0;   // release the next AR
        end else begin
          beat <= beat + 1;
        end
      end
    end
  end

  final begin
    $display("[BURST MASTER] reads=%0d/%0d  total R beats=%0d/%0d",
             ridx, M, total_beats, total_expected);
    if (ridx != M)
      $error("[BURST MASTER] only %0d of %0d bursts completed — a burst was stranded.", ridx, M);
    if (total_beats != total_expected)
      $error("[BURST MASTER] got %0d of %0d total beats.", total_beats, total_expected);
  end
endmodule
