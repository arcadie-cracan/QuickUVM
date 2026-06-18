// xrun filelist — vec_unit QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test     -> packed struct + packed array, S1
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen
../gen/vec_unit_tb_pkg.sv
../gen/vu_if.sv
../gen/clkgen.sv

// real combinational DUT (not the generated stub)
../rtl/vec_unit.sv

../gen/tb_top.sv
