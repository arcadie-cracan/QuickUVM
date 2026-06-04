// xrun filelist — sat_adder QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test     -> golden model runs in C via DPI-C
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen
../gen/sat_adder_tb_pkg.sv
../gen/add_if.sv
../gen/clkgen.sv

// real combinational DUT (not the generated stub)
../rtl/sat_adder.sv

../gen/tb_top.sv

// DPI-C golden model (K0)
../gen/sat_adder_reference_model.c
