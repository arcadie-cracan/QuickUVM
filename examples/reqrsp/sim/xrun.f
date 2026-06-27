// xrun filelist — reqrsp QuickUVM A2 two-stream example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen

../gen/reqrsp_tb_pkg.sv
../gen/req_if.sv
../gen/rsp_if.sv
../gen/clkgen.sv

// real DUT (not the generated gen/reqrsp.sv stub)
../rtl/reqrsp.sv

../gen/tb_top.sv
