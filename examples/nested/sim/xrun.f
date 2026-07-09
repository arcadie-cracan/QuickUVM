// xrun filelist — nested QuickUVM H1 3-level hierarchy example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=nested_test
// top 'nested' composes clusterA + clusterB; each cluster composes two leaf blocks.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// leaf block env layers (agent VIP pkg + interface + env pkg)
../gen/ga0_if.sv
../gen/ga0_pkg.sv
../gen/a0_env_pkg.sv
../gen/ga1_if.sv
../gen/ga1_pkg.sv
../gen/a1_env_pkg.sv
../gen/gb0_if.sv
../gen/gb0_pkg.sv
../gen/b0_env_pkg.sv
../gen/gb1_if.sv
../gen/gb1_pkg.sv
../gen/b1_env_pkg.sv

// top test pkg (includes the clusterA/clusterB + top composition classes)
../gen/nested_test_pkg.sv
../gen/clkgen.sv

// real leaf block DUTs
../rtl/a0.sv
../rtl/a1.sv
../rtl/b0.sv
../rtl/b1.sv

../gen/tb_top.sv
