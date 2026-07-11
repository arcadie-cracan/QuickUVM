// xrun filelist — wbx K2 whitebox-probe example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test
// The probe SVA (in wbx_probe_if) + the probe monitor's coverage check/cover the
// DUT's INTERNAL fill_level / FSM state / real accumulator — none of which are ports.
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen

../gen/wbx_tb_pkg.sv
../gen/cmd_if.sv
../gen/wbx_probe_if.sv
../gen/clkgen.sv

// real DUT (its internal signals are observed by the K2 probes)
../rtl/wbx.sv

../gen/tb_top.sv
