// xrun filelist — alu QuickUVM example (run from sim/)
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top
+incdir+../gen
../rtl/alu_pkg.sv
../gen/alu_tb_pkg.sv
../gen/alu_if.sv
../gen/clkgen.sv
../rtl/alu.sv
../gen/tb_top.sv
