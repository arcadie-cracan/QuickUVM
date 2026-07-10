//----------------------------------------------------------------------
// mclk — a two-clock-domain DUT (M1 demo). Two independent registered lanes,
// each in its own clock + reset domain:
//   - sys lane: sys_dout <= sys_din + 1   on posedge clk_sys, cleared by rst_sys_n
//   - io  lane: io_dout  <= io_din ^ 8'hA5 on posedge clk_io,  cleared by rst_io_n
// (One register deep, so the TB monitor's input@posedge / output@next-posedge
// sampling checks it against the pure combinational function of the sampled input.)
//----------------------------------------------------------------------
module mclk (
  output logic [7:0] sys_dout,
  input        [7:0] sys_din,
  output logic [7:0] io_dout,
  input        [7:0] io_din,
  input              clk_sys,
  input              clk_io,
  input              rst_sys_n,
  input              rst_io_n
  );

  always_ff @(posedge clk_sys or negedge rst_sys_n)
    if (!rst_sys_n) sys_dout <= '0;
    else            sys_dout <= sys_din + 1'b1;

  always_ff @(posedge clk_io or negedge rst_io_n)
    if (!rst_io_n) io_dout <= '0;
    else           io_dout <= io_din ^ 8'hA5;

endmodule
