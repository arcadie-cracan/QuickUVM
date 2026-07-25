// Portable compile filelist -- reqrsp.
// Sources + include dirs, NO tool switches: this is the shared input to every
// vendor wrapper (xrun.f / vcs.f / qrun.f) AND the coding-assistance filelist a
// language server consumes (verible --file_list_path, slang -f). Run tools from
// this directory. See docs/filelist_generation_analysis.md.
+incdir+.
// the DUT's real RTL (referenced, not owned by QuickUVM); packages compile
// first. Plain `-f` (universal cwd-relative) — the paths inside it resolve from
// the run directory (this gen/ dir), NOT from the filelist's own location, so
// they must be run-dir-relative or absolute (the `regress.filelist` convention).
// `-F` (file-relative) was tried but is unreliable across vendors (qrun mixes it).
-f ../rtl/reqrsp.f
-f pkg.f
clkgen.sv
tb_top.sv

// Add extra sources or incdirs below (preserved across regeneration):
// pragma quickuvm custom extra_compile_files begin
// pragma quickuvm custom extra_compile_files end
