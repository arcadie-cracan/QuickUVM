// xrun filelist — axi_handshake (valid/ready handshake responder). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/axi_handshake_tb_pkg.sv
../gen/rd_if.sv
../gen/clkgen.sv
../rtl/axi_handshake.sv
../gen/tb_top.sv
