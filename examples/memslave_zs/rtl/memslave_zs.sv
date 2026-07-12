// A ZERO-SLACK bus MASTER: it issues a request and samples the response on the VERY NEXT
// edge. It does not wait. This is the obligation a real serial device imposes, and it is
// the one `memslave` never imposed -- which is why a sequencer-mediated responder passed
// there for weeks while being structurally one cycle too slow.
//
// This is the point of a reactive agent. The DUT drives `req`/`addr`; the TESTBENCH is
// the memory device that must answer with `gnt` and `rdata`. Nothing in the TB initiates.
//
// `gnt` is a per-cycle obligation (the DUT samples it every cycle), which is exactly what
// forces the CONTINUOUS responder shape: a driver that parked between items would leave
// gnt stale and the DUT would hang or double-issue.

module memslave_zs (
  input  logic        clk,
  input  logic        rst_n,

  // DUT -> TB: the request (the TB samples these)
  output logic        req,
  output logic [7:0]  addr,

  // TB -> DUT: the response (the TB drives these)
  input  logic        gnt,
  input  logic [31:0] rdata,

  // observable result
  output logic [31:0] last_data,
  output logic [7:0]  fetched,
  output logic [7:0]  missed    // grants that arrived too late
);

  typedef enum logic [1:0] {IDLE, REQ, DONE} state_e;
  state_e state;
  logic [7:0] ctr;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state     <= IDLE;
      ctr       <= '0;
      req       <= 1'b0;
      addr      <= '0;
      last_data <= '0;
      fetched   <= '0;
      missed    <= '0;
    end else begin
      case (state)
        IDLE: begin
          req   <= 1'b1;
          addr  <= ctr;
          state <= REQ;
        end
        REQ: begin
          // ZERO SLACK. The DUT does NOT wait: it offers exactly ONE cycle, then moves on
          // regardless. `memslave` parks here until it is granted, which is the ONLY reason
          // a sequencer-mediated response is fast enough for it. A real serial device does
          // not wait -- full-duplex SPI drives MISO on the very edge it samples MOSI.
          if (gnt) begin              // the TB granted IN TIME -> capture the response
            last_data <= rdata;
            fetched   <= fetched + 8'd1;
          end else begin
            missed    <= missed + 8'd1;   // ...the TB was too late
          end
          req   <= 1'b0;
          ctr   <= ctr + 8'd1;
          state <= DONE;              // leave UNCONDITIONALLY
        end
        DONE: state <= IDLE;          // a gap, then fetch the next address
        default: state <= IDLE;
      endcase
    end
  end

endmodule
