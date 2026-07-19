// Top (subsystem) test package filelist (H1): every composed block's env
// package, then the top test package. Paths are relative to this gen/ dir.
+incdir+.
-f add_env_pkg.f
-f inv_env_pkg.f
-f host_pkg.f
// Extra top test sources (preserved on regen):
// pragma quickuvm custom test_pkg_extra_files begin
// pragma quickuvm custom test_pkg_extra_files end
chip_test_pkg.sv
