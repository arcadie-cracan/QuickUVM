// xrun filelist — chip: H2 boundary agents (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=chip_test
// A subsystem with a chip-boundary agent: host drives add -> inv; inv.dout wires
// back to host.resp; the e2e cross-block scoreboard checks inv.dout == ~(host.hin+1).
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// boundary agent (top-level VIP)
../gen/host_if.sv
../gen/host_pkg.sv

// add block — reusable env layer (passive agent)
../gen/a_if.sv
../gen/a_pkg.sv
../gen/add_env_pkg.sv

// inv block — reusable env layer (passive agent)
../gen/b_if.sv
../gen/b_pkg.sv
../gen/inv_env_pkg.sv

// top subsystem: cross-block scoreboard + env + coordination + tests
../gen/chip_test_pkg.sv
../gen/clkgen.sv

// real block DUTs
../add/rtl/add.sv
../inv/rtl/inv.sv

../gen/tb_top.sv
