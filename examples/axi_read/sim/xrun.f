// xrun filelist — axi_read (pipelined, multi-outstanding out-of-order responder). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/axi_read_tb_pkg.sv
../gen/rd_if.sv
../gen/clkgen.sv
../rtl/axi_read.sv
../gen/tb_top.sv
