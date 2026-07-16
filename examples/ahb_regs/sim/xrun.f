// xrun filelist — ahb_regs (RAL over a registered-read AHB-Lite bus). Run from sim/:
//   xrun -f xrun.f +UVM_TESTNAME=ahb_regs_csr_hw_reset_test
//   xrun -f xrun.f +UVM_TESTNAME=ahb_regs_csr_bit_bash_test
//   xrun -f xrun.f +UVM_TESTNAME=ahb_regs_csr_rw_test
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen

// external uvm_reg_block (compiled before the tb package imports it)
../ral/ahb_regs_ral_pkg.sv

../gen/ahb_regs_tb_pkg.sv
../gen/ahb_if.sv
../gen/clkgen.sv

// the real AHB register DUT (not the generated stub)
../rtl/ahb_regs.sv

../gen/tb_top.sv
