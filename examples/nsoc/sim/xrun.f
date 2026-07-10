// xrun filelist — nsoc QuickUVM H1 parameterized+reused nested subsystem.
//   run from sim/:  xrun -f xrun.f +UVM_TESTNAME=nsoc_test
// The SAME chan cluster (adder+shifter) reused twice: lo at W=8, hi at W=16.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// lo instance of the chan cluster (W=8): leaf env layers
../gen/lo_a_if.sv
../gen/lo_a_pkg.sv
../gen/lo_add_env_pkg.sv
../gen/lo_s_if.sv
../gen/lo_s_pkg.sv
../gen/lo_shl_env_pkg.sv

// hi instance of the chan cluster (W=16): leaf env layers
../gen/hi_a_if.sv
../gen/hi_a_pkg.sv
../gen/hi_add_env_pkg.sv
../gen/hi_s_if.sv
../gen/hi_s_pkg.sv
../gen/hi_shl_env_pkg.sv

// top test pkg (includes lo_chan/hi_chan + nsoc composition classes)
../gen/nsoc_test_pkg.sv
../gen/clkgen.sv

// the reused parameterized RTL modules (instantiated at #(8) and #(16))
../rtl/add.sv
../rtl/shl.sv

../gen/tb_top.sv
