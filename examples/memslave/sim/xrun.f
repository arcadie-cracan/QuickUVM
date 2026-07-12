// xrun filelist — memslave (reactive/responder agent). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/memslave_tb_pkg.sv
../gen/mem_if.sv
../gen/clkgen.sv
../rtl/memslave.sv
../gen/tb_top.sv
