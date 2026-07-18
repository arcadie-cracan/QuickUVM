// xrun filelist — nchan (I-9 `count`: N agents into one vectored DUT). Run from sim/:
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/nchan_tb_pkg.sv
../gen/ch_if.sv
../gen/clkgen.sv

// the real N-channel DUT (not the generated stub gen/nchan.sv)
../rtl/nchan.sv

../gen/tb_top.sv
