// xrun filelist — cdc_fifo (cross-domain-integrity scoreboard). Run from sim/:
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/cdc_fifo_tb_pkg.sv
../gen/wr_if.sv
../gen/rd_if.sv
../gen/clkgen.sv
../rtl/cdc_fifo.sv
../gen/tb_top.sv
