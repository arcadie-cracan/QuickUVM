// xrun filelist — packet QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test     -> var-length payload, S1
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen
../gen/pkt_sum_tb_pkg.sv
../gen/stream_if.sv
../gen/clkgen.sv

// real combinational DUT (not the generated stub)
../rtl/pkt_sum.sv

../gen/tb_top.sv
