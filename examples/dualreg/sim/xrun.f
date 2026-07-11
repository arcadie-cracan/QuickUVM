// xrun filelist — dualreg QuickUVM M1 multi agent-driven reset example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=dualreg_test
// Two registered lanes on one clock, each reset driven by ITS OWN agent's sequences:
// agent a drives an active-low reset (a_rst_n), agent b an active-high reset (b_rst).
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/dualreg_tb_pkg.sv
../gen/a_if.sv
../gen/b_if.sv
../gen/clkgen.sv

// real DUT (not the generated gen/dualreg.sv stub)
../rtl/dualreg.sv

../gen/tb_top.sv
