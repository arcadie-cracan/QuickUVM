// Environment package filelist (F2): the agent VIPs + the env package.
// Paths are relative to this gen/ directory.
+incdir+.
// F2' — agent 'io' is consumed BY REFERENCE from an external VIP. Its
// package is NOT regenerated here; chain the VIP's own filelist with -F (paths resolve
// relative to that file's directory).
-F ../../f2_iovip/gen/io_pkg.f
// Extra sources the env package needs, compiled before it (preserved on regen):
// pragma quickuvm custom env_pkg_extra_files begin
// pragma quickuvm custom env_pkg_extra_files end
f2_con_env_pkg.sv
