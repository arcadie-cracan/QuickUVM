// xrun filelist — priority_encoder QuickUVM example (run from sim/)
-uvm
-access +rwc
-timescale 1ns/1ns
-linedebug
-top tb_top
+incdir+../gen
../gen/priority_encoder_tb_pkg.sv
../gen/pe_if.sv
../gen/clkgen.sv
../rtl/priority_encoder.sv
../gen/tb_top.sv
