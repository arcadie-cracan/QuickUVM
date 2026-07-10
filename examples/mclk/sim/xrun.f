// xrun filelist — mclk QuickUVM M1 multi-clock / multi-reset example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=mclk_test
// Two clock domains (clk_sys @10, clk_io @6) each with its own external reset; the
// parameterized clkgen is instantiated once per domain by tb_top.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

../gen/mclk_tb_pkg.sv
../gen/sys_if.sv
../gen/io_if.sv
../gen/clkgen.sv

// real DUT (not the generated gen/mclk.sv stub)
../rtl/mclk.sv

../gen/tb_top.sv
