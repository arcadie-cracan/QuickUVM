// Top (subsystem) test package filelist (H1): every composed block's env
// package, then the top test package. Paths are relative to this gen/ dir.
+incdir+.
-f left_src_env_pkg.f
-f left_snk_env_pkg.f
-f right_src_env_pkg.f
-f right_snk_env_pkg.f
// Extra top test sources (preserved on regen):
// pragma quickuvm custom test_pkg_extra_files begin
// pragma quickuvm custom test_pkg_extra_files end
dsoc_test_pkg.sv
