// xrun filelist — gated_add QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test      -> bias held 0, y == a
//   xrun -f xrun.f +UVM_TESTNAME=bias_on_test   -> bias re-enabled, y == a+bias
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen
../gen/gated_add_tb_pkg.sv
../gen/src_if.sv
../gen/clkgen.sv

// real combinational DUT (not the generated stub)
../rtl/gated_add.sv

../gen/tb_top.sv
