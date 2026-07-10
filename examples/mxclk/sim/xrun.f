// xrun filelist — mxclk QuickUVM M1 mixed-unit clocks example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=mxclk_test
// Two clock domains in different units (clk_fast @500ps, clk_slow @10ns); QuickUVM
// resolves one -timescale at the finest unit (ps) and scales both periods.
-uvm
-access +rwc
-timescale 1ps/1ps
-top tb_top

+incdir+../gen

../gen/mxclk_tb_pkg.sv
../gen/fast_if.sv
../gen/slow_if.sv
../gen/clkgen.sv

// real DUT (not the generated gen/mxclk.sv stub)
../rtl/mxclk.sv

../gen/tb_top.sv
