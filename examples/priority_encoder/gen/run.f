-timescale 1ns/1ns
-f pkg.f
+incdir+..
clkgen.sv
priority_encoder.sv
tb_top.sv
-y . +libext+.sv

// Add extra sim args, incdirs or sources below (preserved across regeneration):
// pragma quickuvm custom extra_run_args begin
// pragma quickuvm custom extra_run_args end
