//----------------------------------------------------------------------
// mul — a clocked leaf: registered dout = din << 1 on posedge clk, cleared by rst_n.
// Runs on its own 8 ns clock domain (independent of acc's 10 ns domain).
//----------------------------------------------------------------------
module mul (
  output logic [7:0] dout,
  input        [7:0] din,
  input              clk,
  input              rst_n
  );
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) dout <= '0;
    else        dout <= din << 1;
endmodule
