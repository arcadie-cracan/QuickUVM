// xrun filelist — axi_slave (full AXI slave: read agent + write agent on one DUT). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/axi_slave_tb_pkg.sv
../gen/rd_if.sv
../gen/wr_if.sv
../gen/clkgen.sv
../rtl/axi_slave.sv
../gen/tb_top.sv
