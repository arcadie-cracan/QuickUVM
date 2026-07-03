// Top (subsystem) run filelist (H1). Run from this gen/ directory:
//   xrun -uvm -access +rwc -f run.f +UVM_TESTNAME=psoc_test
-timescale 1ns/1ns
-top tb_top
+incdir+.
-f psoc_test_pkg.f
clkgen.sv
// Real block DUTs — a subsystem does NOT emit per-block DUT stubs, so list each
// composed block's RTL here (compiled before tb_top):
// pragma quickuvm custom subenv_dut_sources begin
// pragma quickuvm custom subenv_dut_sources end
tb_top.sv

// Add extra sim args, incdirs or sources below (preserved across regeneration):
// pragma quickuvm custom extra_run_args begin
// pragma quickuvm custom extra_run_args end
