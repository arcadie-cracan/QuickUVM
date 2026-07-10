-timescale 1ps/1ps
-f pkg.f
+incdir+..
clkgen.sv
mxclk.sv
tb_top.sv
-y . +libext+.sv

// Add extra sim args, incdirs or sources below (preserved across regeneration):
// pragma quickuvm custom extra_run_args begin
// pragma quickuvm custom extra_run_args end
