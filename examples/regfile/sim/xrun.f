// xrun filelist — regfile QuickUVM C5 / RAL example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=regfile_csr_hw_reset_test
//   xrun -f xrun.f +UVM_TESTNAME=regfile_csr_bit_bash_test
//   xrun -f xrun.f +UVM_TESTNAME=regfile_csr_rw_test
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen

// external uvm_reg_block (reggen-style; compiled before the tb package imports it)
../ral/regfile_ral_pkg.sv

../gen/regfile_tb_pkg.sv
../gen/host_if.sv
../gen/clkgen.sv

// real register DUT (not the generated stub)
../rtl/regfile.sv

../gen/tb_top.sv
