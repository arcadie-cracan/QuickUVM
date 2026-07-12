// xrun filelist — hmac QuickUVM example (T1). Run from sim/.
//   xrun -f xrun.f +UVM_TESTNAME=hmac_test   -> the RFC 4231 vector, checked by the
//                                               generated scoreboard vs the C model
//   xrun -f xrun.f +UVM_TESTNAME=rand_test   -> random register traffic
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top

+incdir+../gen
+incdir+../rtl/vendor
+incdir+../dpi

// the vendored C golden model (OpenTitan cryptoc, Apache-2.0)
../dpi/cryptoc_dpi_pkg.sv
../dpi/util.c
../dpi/sha.c
../dpi/sha256.c
../dpi/sha384.c
../dpi/sha512.c
../dpi/hmac.c
../dpi/hmac_wrap.c
../dpi/cryptoc_dpi.c

// vendor RTL (unmodified, lowRISC/opentitan)
../rtl/vendor/prim_util_pkg.sv
../rtl/vendor/prim_mubi_pkg.sv
../rtl/vendor/prim_count_pkg.sv
../rtl/vendor/prim_sha2_pkg.sv
../rtl/vendor/prim_count.sv
../rtl/vendor/prim_fifo_sync_cnt.sv
../rtl/vendor/prim_fifo_sync.sv
../rtl/vendor/prim_packer.sv
../rtl/vendor/prim_sha2_pad.sv
../rtl/vendor/prim_sha2.sv
../rtl/vendor/prim_sha2_32.sv
../rtl/vendor/hmac_reg_pkg.sv
../rtl/vendor/hmac_core.sv

// our bus wrapper
../rtl/hmac_reg_generic.sv
../rtl/hmac.sv

// the generated bench
../gen/hmac_tb_pkg.sv
../gen/host_if.sv
../gen/clkgen.sv
../gen/tb_top.sv
