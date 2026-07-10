// xrun filelist — dsoc QuickUVM H1 CROSS-LEVEL into a REUSED (namespaced) subtree.
//   run from sim/:  xrun -f xrun.f +UVM_TESTNAME=dsoc_test
// The SAME `lane` cluster (src + snk) reused twice (left / right), ring-wired
// across the hierarchy: each lane's src drives the OTHER lane's snk.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// left instance of the lane cluster: leaf env layers
../gen/left_src_if.sv
../gen/left_sa_pkg.sv
../gen/left_src_env_pkg.sv
../gen/left_snk_if.sv
../gen/left_ka_pkg.sv
../gen/left_snk_env_pkg.sv

// right instance of the lane cluster: leaf env layers
../gen/right_src_if.sv
../gen/right_sa_pkg.sv
../gen/right_src_env_pkg.sv
../gen/right_snk_if.sv
../gen/right_ka_pkg.sv
../gen/right_snk_env_pkg.sv

// top test pkg (includes left_lane/right_lane + dsoc composition + l2r/r2l)
../gen/dsoc_test_pkg.sv
../gen/clkgen.sv

// the reused RTL modules (one src / one snk, instantiated per lane instance)
../rtl/src.sv
../rtl/snk.sv

../gen/tb_top.sv
