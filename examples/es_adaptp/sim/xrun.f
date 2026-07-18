// xrun filelist — es_adaptp (windowed Adaptive-Proportion health test). Run from sim/:
//   xrun -f xrun.f +UVM_TESTNAME=adaptp_test   -> the directed windows (mutation target)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test     -> random entropy, every window checked
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/es_adaptp_tb_pkg.sv
../gen/es_if.sv
../gen/clkgen.sv

// the real health-test RTL (not the generated stub gen/es_adaptp.sv)
../rtl/es_adaptp.sv

../gen/tb_top.sv
