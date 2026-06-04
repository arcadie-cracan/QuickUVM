// xrun filelist — fifo QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=smoke     -> data-integrity check
//   xrun -f xrun.f +UVM_TESTNAME=stress    -> concurrent soak
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen
../gen/fifo_tb_pkg.sv
../gen/wr_if.sv
../gen/rd_if.sv
../gen/clkgen.sv

// real combinational/sequential DUT (not the generated stub)
../rtl/fifo.sv

../gen/tb_top.sv
