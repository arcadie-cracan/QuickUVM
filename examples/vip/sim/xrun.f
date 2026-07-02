// xrun filelist — vip QuickUVM F2 packaged-layout example (run from sim/).
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
//
// This lists the generated packages directly, in dependency order, so it runs from
// sim/ against the real DUT. The generated per-package filelists (gen/io_pkg.f,
// gen/vip_env_pkg.f, gen/vip_test_pkg.f) are for SEPARATE compilation and resolve
// their nested -f relative to the cwd, so run those from gen/ — e.g. the agent VIP
// alone: `cd ../gen && xrun -uvm -compile -f io_pkg.f`.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// packages in dependency order: agent VIP -> env -> test
../gen/io_if.sv
../gen/io_pkg.sv
../gen/vip_env_pkg.sv
../gen/vip_test_pkg.sv

../gen/clkgen.sv

// real DUT (not the generated gen/vip.sv stub)
../rtl/vip.sv

../gen/tb_top.sv
