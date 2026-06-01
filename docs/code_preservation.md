# Code preservation (pragma sections)

QuickUVM regenerates the whole testbench from your YAML config on every `generate`.
To keep hand-written code across regenerations, write it inside **pragma sections**.

## Marker syntax

```systemverilog
// pragma quickuvm custom <section_name> begin
  // your code here — survives every `quick-uvm generate`
// pragma quickuvm custom <section_name> end
```

- The comment may be `//` (SystemVerilog) **or** `#` (filelists / Makefiles).
- `<section_name>` must be unique within a file.
- Markers must sit on their own line; the generator emits them that way.
- A section whose body is empty (or only the generated default) is treated as
  "untouched" — the freshly rendered default flows through on regen.

## The safety contract (fail-closed)

Modelled on Siemens UVMF's `regen.py`, preservation is **fail-closed**:

| Situation | What happens |
|---|---|
| You edit code inside a fence | Preserved on regen. |
| A section you edited no longer exists in the new template (renamed/removed) | **`generate` aborts** with a "potential loss of hand edits" error, listing the orphaned sections. Re-run with `--allow-drop` to proceed (your edit is dropped but the old file is backed up). |
| A marker is malformed (missing `end`, mismatched name, nested, duplicate) | **`generate` aborts** before writing anything, pointing at the offending line. |
| Any overwrite | A rolling `<file>.bak.<N>` copy is written first — existing backups are never overwritten, so every prior version is kept (disable with `--no-backup`). |

This means a single bad regeneration can never silently lose your code.

## CLI

```bash
quick-uvm generate -c cfg.yaml -o tb/            # fail-closed, writes .bak backups
quick-uvm generate -c cfg.yaml -o tb/ --allow-drop   # proceed past orphaned sections
quick-uvm generate -c cfg.yaml -o tb/ --no-backup    # skip .bak files
quick-uvm status   -c cfg.yaml -o tb/            # classify every file (see below)
```

`status` reports, per file:
- **user-modified** — fenced sections you have edited (will be preserved).
- **ORPHANED (will be LOST)** — edited sections with no home in the new template.
- **out-of-band edits** — changes to *generated* (non-fenced) regions, which a regen
  will overwrite.
- **MALFORMED MARKERS** — a regen would fail closed until fixed.

A clean tree reports "Clean: every file matches the generator."

## Available sections

Empty fences (write custom code here):

| File | Sections |
|---|---|
| `<trans>.svh` | `class_item_additional`, `do_copy_additional`, `do_compare_additional`, `convert2string_additional` |
| `<if>.sv` | `signals_additional`, `clocking_block_additional` |
| `<agent>_driver.svh` | `class_item_additional`, `initialize_additional`, `drive_item_additional` |
| `<agent>_monitor.svh` | `class_item_additional`, `sample_dut_additional` |
| `<agent>_agent.svh` | `class_item_additional`, `build_phase_additional`, `connect_phase_additional` |
| `<agent>_cover.svh` | `class_item_additional`, `coverpoints_additional` |
| `<agent>_sequence.svh` | `class_item_additional`, `do_item_constraints` |
| `env.svh` | `class_item_additional`, `build_phase_additional`, `connect_phase_additional` |
| `test_base.svh` / `<test>.svh` | `class_item_additional`, `build_phase_additional`, `run_phase_additional` |
| `sb_comparator.svh` / `sb_predictor.svh` | `class_item_additional` |
| `tb_pkg.sv` | `imports`, `sequences_additional` |
| `top.sv` | `dut_connections` |
| `pkg.f` / `run.f` | `extra_pkg_files`, `extra_run_args` |

Fences that ship with a **default body** you are expected to replace in place
(your edits override the default; an untouched default is regenerated):

| File | Section |
|---|---|
| `<dut>.sv` | `dut_logic` |
| `sb_calc_exp.svh` | `prediction_logic` |
