// xrun filelist — spi_device (prefetch responder on a DUT-driven clock). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
../gen/spi_host_tb_pkg.sv
../gen/spi_if.sv
../gen/clkgen.sv
../rtl/spi_host.sv
../gen/tb_top.sv
