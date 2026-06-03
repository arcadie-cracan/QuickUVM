// xrun filelist — alu QuickUVM example (run from sim/)
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top top
+incdir+../gen
../rtl/alu_pkg.sv
../gen/tb_pkg.sv
../gen/alu_if.sv
../gen/clkgen.sv
../rtl/alu.sv
../gen/top.sv
