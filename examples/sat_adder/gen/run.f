-timescale 1ns/1ns
-f pkg.f
+incdir+..
clkgen.sv
sat_adder.sv
tb_top.sv
sat_adder_reference_model.c
-y . +libext+.sv

// Add extra sim args, incdirs or sources below (preserved across regeneration):
// pragma quickuvm custom extra_run_args begin
// pragma quickuvm custom extra_run_args end
