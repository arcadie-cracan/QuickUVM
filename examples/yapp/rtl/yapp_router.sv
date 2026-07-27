//----------------------------------------------------------------------
// YAPP-style packet router (tutorial DUT).
// One input channel routes each valid packet to one of three output
// channels by its 2-bit address: 0/1/2 select a port, 3 = drop.
// One-cycle registered latency; synchronous outputs, async active-low reset.
//----------------------------------------------------------------------
module yapp_router (
  input  logic       clk,
  input  logic       rst_n,
  // input channel
  input  logic       in_valid,
  input  logic [1:0] in_addr,
  input  logic [7:0] in_data,
  // three output channels
  output logic       out0_valid,
  output logic [7:0] out0_data,
  output logic       out1_valid,
  output logic [7:0] out1_data,
  output logic       out2_valid,
  output logic [7:0] out2_data
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      out0_valid <= 1'b0; out1_valid <= 1'b0; out2_valid <= 1'b0;
      out0_data  <= 8'h0; out1_data  <= 8'h0; out2_data  <= 8'h0;
    end else begin
      out0_valid <= in_valid && (in_addr == 2'd0);
      out1_valid <= in_valid && (in_addr == 2'd1);
      out2_valid <= in_valid && (in_addr == 2'd2);
      out0_data  <= in_data;
      out1_data  <= in_data;
      out2_data  <= in_data;
    end
  end
endmodule
