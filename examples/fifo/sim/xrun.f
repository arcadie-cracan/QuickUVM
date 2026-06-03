// xrun filelist — fifo QuickUVM example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=smoke     -> data-integrity check
//   xrun -f xrun.f +UVM_TESTNAME=stress    -> concurrent soak
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top top

+incdir+../gen
../gen/tb_pkg.sv
../gen/wr_if.sv
../gen/rd_if.sv
../gen/clkgen.sv

// real combinational/sequential DUT (not the generated stub)
../rtl/fifo.sv

../gen/top.sv
