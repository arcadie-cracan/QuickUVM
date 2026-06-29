// xrun filelist — splitter QuickUVM A2 multi-transaction-type example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen

../gen/splitter_tb_pkg.sv
../gen/req_if.sv
../gen/cha_if.sv
../gen/chb_if.sv
../gen/clkgen.sv

// real DUT (not the generated gen/splitter.sv stub)
../rtl/splitter.sv

../gen/tb_top.sv
