// xrun filelist — xpipe QuickUVM H1 CROSS-LEVEL connections + scoreboards.
//   run from sim/:  xrun -f xrun.f +UVM_TESTNAME=xpipe_test
// A cross-level wire reaches into two clusters (stg1.add.dout -> stg2.inv.din)
// and a cross-level scoreboard xchk predicts inv.dout = ~(add.dout).
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// stg1 cluster leaf env layers (add + dbl)
../gen/a_if.sv
../gen/a_pkg.sv
../gen/add_env_pkg.sv
../gen/d_if.sv
../gen/d_pkg.sv
../gen/dbl_env_pkg.sv

// stg2 cluster leaf env layers (inv + xr)
../gen/b_if.sv
../gen/b_pkg.sv
../gen/inv_env_pkg.sv
../gen/x_if.sv
../gen/x_pkg.sv
../gen/xr_env_pkg.sv

// top test pkg (includes stg1/stg2 cluster classes + xpipe composition + xchk)
../gen/xpipe_test_pkg.sv
../gen/clkgen.sv

// the composed block RTL modules
../rtl/add.sv
../rtl/dbl.sv
../rtl/inv.sv
../rtl/xr.sv

../gen/tb_top.sv
