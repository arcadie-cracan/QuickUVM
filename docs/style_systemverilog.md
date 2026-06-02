# SystemVerilog / UVM style — the generated output

This governs the **product**: the SystemVerilog/UVM that QuickUVM emits. It matters more
than the Python style — every user reads it, and it must be both *industrial-trustworthy*
and *clear enough to teach from*. The templates ([`quick_uvm/templates/`](../quick_uvm/templates/))
are the single source of truth; this document is the spec they implement.

## Baseline & references

- **Canonical baseline: Cliff Cummings / Sunburst Design (Paradigm Works) SV & UVM
  coding guidelines.** QuickUVM's templates already follow the
  [`uvmtb_template`](https://github.com/cliffordcummings/uvmtb_template) style, so this is
  zero-migration and keeps the output pedagogically clear.
- **Secondary reference (where Cummings is silent): lowRISC / OpenTitan** Verilog & DV
  style guides — the most complete public, production-proven, machine-checkable style.
- **Authority for class/API names: Accellera UVM / IEEE 1800.2.**

When the references disagree, Cummings wins for layout/idiom; lowRISC fills gaps.

## Enforcement (the hard gate)

Prose style guides rot. The product is gated in CI by **Verible** (open-source), so every
release ships lint-clean, consistently-formatted UVM:

- `verible-verilog-lint --rules_config .verible-lint.rules` — style lint.
- `verible-verilog-format --column_limit=100 --verify` — formatting.

Both run against the generated example in the `generated-sv` CI job
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)). To silence a rule that
doesn't fit generated UVM, edit [`.verible-lint.rules`](../.verible-lint.rules) with a
one-line rationale — **never** weaken the generated code to appease a rule.
[DVT](https://www.dvteclipse.com/) is great for interactive authoring lint locally, but
Verible is the headless CI authority.

## Formatting

- **100-column** line limit (lint rule `line-length` + formatter `--column_limit=100`).
- Two-space indent; one statement per line (no run-on lines — see
  [`style_templates.md`](style_templates.md), the `{%-` lesson).
- `lower_snake_case` for signals, variables, class names, file names; `UPPER_CASE` for
  parameters, localparams, and `` `macros ``.

## Naming conventions

Files/classes are `lower_snake_case` with a **role suffix**:

| Component | Suffix / name | Example |
|---|---|---|
| Transaction (sequence item) | `_seq_item` | `reg_seq_item` |
| Agent | `_agent` | `reg_agent` |
| Driver | `_driver` | `reg_driver` |
| Monitor | `_monitor` | `reg_monitor` |
| Sequencer | `_sequencer` | `reg_sequencer` |
| Sequence | `_sequence` / `_seq` | `reg_sequence` |
| Agent config | `_config` | `reg_config` |
| Environment | `env` | `env` |
| Env config | `env_config` | `env_config` |
| Coverage collector | `_cover` | `reg_cover` |
| Scoreboard | `_scoreboard` / `sb_*` | `tb_scoreboard`, `sb_comparator` |
| Test | `_test` / `test_*` | `test_base`, `test_rand` |
| Register adapter | `_adapter` | `reg_adapter` |

> **Transaction suffix: `_seq_item`** (project decision) — it names the UVM concept (a
> `uvm_sequence_item`) precisely. The `transaction:` field in the YAML config sets it;
> `quick-uvm init` scaffolds `<agent>_seq_item`. (Historically the templates used
> `_trans`; `_seq_item` is the convention going forward.)

Handles / members:

- virtual interface handle: `vif`
- analysis port: `<name>_ap` · analysis export: `<name>_export` · TLM fifo: `<name>_fifo`
- clocking block: `cb*` (e.g. `cb1`)

## Structure (Paradigm-Works flat-package style — today's default)

- All components are included into a single `tb_pkg.sv` (the `layout: packaged` option is
  roadmapped in [`parity_roadmap.md`](parity_roadmap.md), phase F2).
- Interfaces passed via `uvm_config_db` (was `uvm_resource_db` before v0.3.0/F1).
- Clocking-block-driven I/O; `extern` method bodies in separate `.svh` files.
- Every generated file carries a banner header (license + "generated — edit only inside
  pragma regions"); user code lives in pragma sections (see
  [`code_preservation.md`](code_preservation.md)).

## Generator-specific rules

- **Deterministic output**: stable ordering of fields/files so regeneration diffs are
  minimal and reviewable.
- **Default skeletons encode good patterns** (reset-gated driver start, envelope-bounded
  monitor sampling) — see `parity_roadmap.md` phase X0; a bad default ships to every user.
