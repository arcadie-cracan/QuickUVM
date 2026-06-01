# QuickUVM vs. other UVM testbench generators

A focused comparison, emphasising **user-code preservation** across regeneration.

## Tools compared

- **QuickUVM** (this project) — Python/Jinja2, Paradigm-Works flat-package style.
- **Siemens UVM Framework (UVMF)** 2026.1 — Python/Jinja2, the design model for our
  pragma mechanism (`templates/python/uvmf_yaml/regen.py`).
- **Doulos Easier UVM Code Generator** — Perl (`easier_uvm_gen.pl`); the
  separate-include-file school of preservation.
- **icdk `uvmgen`** (Dragon-Git) — Python/Mako.
- **`gen_uvm`** (asicnet) — Python rewrite of Easier UVM.

## Preservation strategy

| Tool | Mechanism | Orphaned user code | Backup |
|---|---|---|---|
| **QuickUVM** | in-file pragma fences (`// pragma quickuvm custom …`) | **fail-closed** (error unless `--allow-drop`) | `<file>.bak` |
| **UVMF** | in-file pragma fences (`// \| # pragma uvmf custom …`) | fail-closed (`--merge_skip_missing_blocks` to override) | `_bak_<N>` tree |
| **Doulos Easier UVM** | user code in separate `./include/*.sv` files + factory overrides | n/a (user files never regenerated) | n/a |
| **icdk uvmgen** | none — unconditional overwrite | code lost | none |
| **gen_uvm** | none evident (Easier-UVM include flow not retained) | code lost | none |

QuickUVM and UVMF are the two in-file-fence implementations; QuickUVM now matches
UVMF's fail-closed safety semantics (validate markers → detect orphans → backup →
refuse-or-`--allow-drop`). Doulos is safe by construction (separate files) but pushes
all customization into include files + factory overrides. icdk uvmgen and gen_uvm
overwrite hand edits.

## Capability matrix

| | QuickUVM | UVMF | Doulos | icdk uvmgen | gen_uvm |
|---|---|---|---|---|---|
| Language / templating | Python / Jinja2 | Python / Jinja2 | Perl | Python / Mako | Python |
| Config input | YAML (Pydantic) | YAML (voluptuous) | `key=value` files | JSON/YAML/TOML/XML | `entity_desc.txt` (+VHDL) |
| Register model (RAL) | ✗ (planned) | ✓ | ✓ | ✓ (`ral_pkg`) | ✗ |
| Hierarchical sub-envs | ✗ | ✓ | partial | ✗ | ✗ |
| Parameterized interfaces | ✗ | ✓ | partial | ✓ | ✗ |
| Multi-simulator run infra | minimal (`.f` files) | ✓ (per-sim makefiles, testlists) | ✓ | ✓ | ✓ |
| Code-preservation safety | **fail-closed + backup** | fail-closed + backup | separate files | none | none |
| Footprint | tiny, hackable | large framework | medium | medium | small |

## Where QuickUVM stands

**Strengths:** clean Pydantic-validated config; small, readable, MIT codebase; the
flat Cliff-Cummings style is pedagogically clear; preservation now has UVMF-grade
safety (better than icdk/gen_uvm, which have none).

**Gaps (roadmapped in `action_plan.md`):**
1. **No register model** — the biggest functional gap, and the most relevant for the
   SPI bridge whose core is register access (generated via `reggen`).
2. Single flat agent topology; scoreboard hardwired to the first agent.
3. No interface/transaction parameterization.
4. Minimal run/regression infrastructure (vs. UVMF's per-simulator makefiles + testlists).

## Notable finding from this comparison work

Auditing QuickUVM against UVMF surfaced that the pragma feature was *advertised but
largely non-functional*: aggressive Jinja `{%-` whitespace trimming glued generated
code onto the marker lines, so the old merger could not extract most sections — and in
the monitor it silently **commented out the DUT-sampling assignments**. Both the
preservation engine and the templates have since been corrected and locked down with
regression tests.
