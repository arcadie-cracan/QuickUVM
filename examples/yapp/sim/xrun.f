// xrun filelist — yapp_router QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top
+incdir+../gen
../gen/yapp_router_tb_pkg.sv
../gen/pkt_if.sv
../gen/clkgen.sv
../rtl/yapp_router.sv
../gen/tb_top.sv
