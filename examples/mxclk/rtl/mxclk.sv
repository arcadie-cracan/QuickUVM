//----------------------------------------------------------------------
// mxclk — a two-clock-domain DUT whose domains use DIFFERENT time units
// (M1 mixed-unit demo). A fast lane clocked at 500 ps and a slow lane at 10 ns;
// QuickUVM emits one -timescale at the finest unit (ps) and scales both periods.
//   - fast lane: fast_dout <= fast_din + 1   on posedge clk_fast, cleared by rst_f
//   - slow lane: slow_dout <= slow_din << 1  on posedge clk_slow, cleared by rst_s
//----------------------------------------------------------------------
module mxclk (
  output logic [7:0] fast_dout,
  input        [7:0] fast_din,
  output logic [7:0] slow_dout,
  input        [7:0] slow_din,
  input              clk_fast,
  input              clk_slow,
  input              rst_f,
  input              rst_s
  );

  always_ff @(posedge clk_fast or negedge rst_f)
    if (!rst_f) fast_dout <= '0;
    else        fast_dout <= fast_din + 1'b1;

  always_ff @(posedge clk_slow or negedge rst_s)
    if (!rst_s) slow_dout <= '0;
    else        slow_dout <= slow_din << 1;

endmodule
