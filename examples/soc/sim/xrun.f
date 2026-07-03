// xrun filelist — soc QuickUVM H1 sub-environments example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=soc_test
// One subsystem bench composing two block envs (adder + inverter), each with
// its own agent, DUT and scoreboard, coordinated by a top virtual sequence.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// adder block — reusable env layer (agent VIP + env package)
../gen/a_if.sv
../gen/a_pkg.sv
../gen/adder_env_pkg.sv

// inverter block — reusable env layer
../gen/b_if.sv
../gen/b_pkg.sv
../gen/inverter_env_pkg.sv

// top subsystem: env + coordination + tests
../gen/soc_test_pkg.sv
../gen/clkgen.sv

// real block DUTs (a subsystem does not emit per-block DUT stubs)
../adder/rtl/adder.sv
../inverter/rtl/inverter.sv

../gen/tb_top.sv
