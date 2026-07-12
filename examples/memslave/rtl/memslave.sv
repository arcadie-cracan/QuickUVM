// A DUT that is a bus MASTER: it issues read requests and consumes the responses.
//
// This is the point of a reactive agent. The DUT drives `req`/`addr`; the TESTBENCH is
// the memory device that must answer with `gnt` and `rdata`. Nothing in the TB initiates.
//
// `gnt` is a per-cycle obligation (the DUT samples it every cycle), which is exactly what
// forces the CONTINUOUS responder shape: a driver that parked between items would leave
// gnt stale and the DUT would hang or double-issue.

module memslave (
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
  output logic [7:0]  fetched
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
    end else begin
      case (state)
        IDLE: begin
          req   <= 1'b1;
          addr  <= ctr;
          state <= REQ;
        end
        REQ: begin
          if (gnt) begin              // the TB granted -> capture the response
            last_data <= rdata;
            fetched   <= fetched + 8'd1;
            req       <= 1'b0;
            ctr       <= ctr + 8'd1;
            state     <= DONE;
          end
        end
        DONE: state <= IDLE;          // a gap, then fetch the next address
        default: state <= IDLE;
      endcase
    end
  end

endmodule
