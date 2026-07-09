module b0 (output logic [7:0] dout, input [7:0] din);
  assign dout = din << 1;
endmodule
