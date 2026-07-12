// xrun filelist — odbus (bidirectional / open-drain `inouts`). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/odbus_tb_pkg.sv
../gen/bus_if.sv
../gen/clkgen.sv
../rtl/odbus.sv
../gen/tb_top.sv
