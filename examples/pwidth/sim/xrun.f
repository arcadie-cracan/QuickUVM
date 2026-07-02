// xrun filelist — pwidth QuickUVM C3 parameterized-VIP example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/pwidth_tb_pkg.sv
../gen/io_if.sv
../gen/clkgen.sv

// real DUT (not the generated gen/pwidth.sv stub)
../rtl/pwidth.sv

../gen/tb_top.sv
