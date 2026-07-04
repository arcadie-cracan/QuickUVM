// xrun filelist — channels QuickUVM H1 same-block-reused-at-N-widths example.
//   run from sim/:  xrun -f xrun.f +UVM_TESTNAME=channels_test
// One parameterized `chan` block config, composed twice: lo at W=8, hi at W=16.
// QuickUVM auto-namespaces the two copies (lo_*/hi_*); both reuse the same RTL
// module `chan`, instantiated as chan#(8) and chan#(16).
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// lo instance (namespaced env layer, W=8)
../gen/lo_c_if.sv
../gen/lo_c_pkg.sv
../gen/lo_chan_env_pkg.sv

// hi instance (namespaced env layer, W=16)
../gen/hi_c_if.sv
../gen/hi_c_pkg.sv
../gen/hi_chan_env_pkg.sv

// top subsystem
../gen/channels_test_pkg.sv
../gen/clkgen.sv

// the ONE reused parameterized DUT module (instantiated at #(8) and #(16))
../chan/rtl/chan.sv

../gen/tb_top.sv
