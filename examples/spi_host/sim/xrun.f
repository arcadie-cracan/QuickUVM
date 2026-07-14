// xrun filelist — spi_host (OpenTitan's real SPI controller). Run from sim/.
-uvm
-access +rwc
-timescale 1ns/1ns
-top tb_top
+incdir+../gen
+incdir+../rtl/vendor
../rtl/vendor/prim_util_pkg.sv
../rtl/vendor/prim_count_pkg.sv
../rtl/vendor/spi_host_cmd_pkg.sv
../rtl/vendor/spi_host_reg_pkg.sv
../rtl/vendor/prim_buf.sv
../rtl/vendor/prim_sec_anchor_buf.sv
../rtl/vendor/prim_flop.sv
../rtl/vendor/prim_flop_en.sv
../rtl/vendor/prim_sparse_fsm_flop.sv
../rtl/vendor/prim_count.sv
../rtl/vendor/prim_fifo_sync_cnt.sv
../rtl/vendor/prim_fifo_sync.sv
../rtl/vendor/prim_packer_fifo.sv
../rtl/vendor/prim_intr_hw.sv
../rtl/vendor/spi_host_shift_register.sv
../rtl/vendor/spi_host_byte_select.sv
../rtl/vendor/spi_host_byte_merge.sv
../rtl/vendor/spi_host_fsm.sv
../rtl/vendor/spi_host_core.sv
../rtl/vendor/spi_host_data_fifos.sv
../rtl/vendor/spi_host_command_queue.sv
../rtl/spi_host_reg_generic.sv
../rtl/spi_host_ot.sv
../gen/spi_host_ot_tb_pkg.sv
../gen/regbus_if.sv
../gen/sdio_if.sv
../gen/clkgen.sv
../gen/tb_top.sv
