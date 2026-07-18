// xrun filelist — hybrid_alert (a HYBRID initiator+responder agent). Run from sim/:
//   xrun -f xrun.f +UVM_TESTNAME=hybrid_test
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/hybrid_alert_tb_pkg.sv
../gen/sndr_if.sv
../gen/clkgen.sv

// the real DUT (not the generated stub gen/hybrid_alert.sv)
../rtl/hybrid_alert.sv

../gen/tb_top.sv
