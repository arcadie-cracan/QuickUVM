// xrun filelist — memslave_zs (ZERO-SLACK responder). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/memslave_zs_tb_pkg.sv
../gen/mem_if.sv
../gen/clkgen.sv
../rtl/memslave_zs.sv
../gen/tb_top.sv
