// xrun filelist — pipe QuickUVM H1 cross-block-scoreboard example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=pipe_test
// A subsystem pipeline: stage 1 (add) feeds stage 2 (inv) via a top connection;
// a cross-block scoreboard checks inv.dout == ~(add.dout).
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// stage 1 (add) — reusable env layer
../gen/a_if.sv
../gen/a_pkg.sv
../gen/add_env_pkg.sv

// stage 2 (inv) — reusable env layer (passive agent)
../gen/b_if.sv
../gen/b_pkg.sv
../gen/inv_env_pkg.sv

// top subsystem: cross-block scoreboard + env + coordination + tests
../gen/pipe_test_pkg.sv
../gen/clkgen.sv

// real block DUTs
../add/rtl/add.sv
../inv/rtl/inv.sv

../gen/tb_top.sv
