// xrun filelist — twowidth QuickUVM C3 multi-instantiation example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
// ONE parameterized VIP, instantiated at W=8 and W=16 in a single bench.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/twowidth_tb_pkg.sv
../gen/io_if.sv
../gen/clkgen.sv

// real DUT (parameterized) — instantiated as twowidth#(8) and twowidth#(16)
../rtl/twowidth.sv

../gen/tb_top.sv
