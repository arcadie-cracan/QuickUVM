// xrun filelist — psoc QuickUVM H1 parameter-propagation example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=psoc_test
// A subsystem composing two PARAMETERIZED blocks, propagated to different widths:
// dp at W=8, mac at W=16.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// dp block (parameterized VIP + env), generated at W=8
../gen/d_if.sv
../gen/d_pkg.sv
../gen/dp_env_pkg.sv

// mac block (parameterized VIP + env), generated at W=16
../gen/m_if.sv
../gen/m_pkg.sv
../gen/mac_env_pkg.sv

// top subsystem
../gen/psoc_test_pkg.sv
../gen/clkgen.sv

// real parameterized block DUTs — instantiated as dp#(8) and mac#(16)
../dp/rtl/dp.sv
../mac/rtl/mac.sv

../gen/tb_top.sv
