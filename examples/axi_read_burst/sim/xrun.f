// xrun filelist — axi_read_burst (multi-beat burst read responder). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/axi_read_burst_tb_pkg.sv
../gen/rd_if.sv
../gen/clkgen.sv
../rtl/axi_read_burst.sv
../gen/tb_top.sv
