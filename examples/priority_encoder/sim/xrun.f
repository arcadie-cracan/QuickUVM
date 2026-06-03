// xrun filelist — priority_encoder QuickUVM example (run from sim/)
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top top
+incdir+../gen
../gen/tb_pkg.sv
../gen/pe_if.sv
../gen/clkgen.sv
../rtl/priority_encoder.sv
../gen/top.sv
