// xrun filelist — axi_write (pipelined write responder: AW + W -> B, out-of-order). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/axi_write_tb_pkg.sv
../gen/wr_if.sv
../gen/clkgen.sv
../rtl/axi_write.sv
../gen/tb_top.sv
