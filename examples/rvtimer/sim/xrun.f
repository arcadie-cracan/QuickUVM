// xrun filelist — rvtimer QuickUVM maturity-assessment example (run from sim/)
//   xrun -f xrun.f +UVM_TESTNAME=rand_test                 -> data-path + directed timer
//   xrun -f xrun.f +UVM_TESTNAME=rvtimer_csr_hw_reset_test
//   xrun -f xrun.f +UVM_TESTNAME=rvtimer_csr_bit_bash_test
//   xrun -f xrun.f +UVM_TESTNAME=rvtimer_csr_rw_test
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top

+incdir+../gen

// external uvm_reg_block (reggen-style; compiled before the tb package imports it)
../ral/rvtimer_ral_pkg.sv

../gen/rvtimer_tb_pkg.sv
../gen/host_if.sv
../gen/irq_if.sv
../gen/clkgen.sv

// real timer DUT (not the generated stub)
../rtl/rvtimer.sv

../gen/tb_top.sv
