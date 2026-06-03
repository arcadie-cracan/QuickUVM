// xrun filelist — barrel_shifter QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top top

+incdir+../gen
../gen/tb_pkg.sv
../gen/bs_if.sv
../gen/clkgen.sv

// real combinational DUT (not the generated stub)
../rtl/barrel_shifter.sv

../gen/top.sv
