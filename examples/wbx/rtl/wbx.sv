//----------------------------------------------------------------------
// wbx — a tiny command-processed FIFO block for the K2 whitebox-probe example.
//
// The state that matters is INTERNAL and NOT exposed at the ports: `fill_level`
// (FIFO occupancy), `state` (an FSM enum), and `acc` (a real accumulator summing
// pushed data). Only `busy` is a port. The testbench OBSERVES the internals via
// K2 probes (hierarchical taps) and asserts/covers them.
//
// SPDX-License-Identifier: MIT
//----------------------------------------------------------------------
module wbx #(
    parameter int DEPTH = 4,
    parameter int DW    = 8
) (
    input  logic          clk,
    input  logic          rst_n,
    input  logic          push,
    input  logic [DW-1:0] data,
    input  logic          pop,
    output logic          busy
);
  typedef enum logic [1:0] {IDLE, BUSY, FULL} state_e;

  state_e            state;       // internal FSM       (probed)
  logic [2:0]        fill_level;  // internal occupancy (probed); 0..DEPTH fits in 3b
  real               acc;         // internal accumulator (probed)

  wire do_push = push && (fill_level < DEPTH[2:0]);
  wire do_pop  = pop  && (fill_level > 3'd0);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      fill_level <= 3'd0;
      acc        <= 0.0;
    end else begin
      unique case ({do_push, do_pop})
        2'b10:   fill_level <= fill_level + 3'd1;
        2'b01:   fill_level <= fill_level - 3'd1;
        default: fill_level <= fill_level;  // both, or neither
      endcase
      if (do_push) acc <= acc + real'(data);
    end
  end

  always_comb begin
    if (fill_level == 3'd0)             state = IDLE;
    else if (fill_level == DEPTH[2:0])  state = FULL;
    else                                state = BUSY;
  end

  assign busy = (state != IDLE);
endmodule
