// xrun filelist — alert_array (compose count + hybrid: N hybrid alert-senders, one DUT).
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/alert_array_tb_pkg.sv
../gen/sndr_if.sv
../gen/clkgen.sv

// the real N-channel DUT (not the generated stub)
../rtl/alert_array.sv

../gen/tb_top.sv
