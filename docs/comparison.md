# QuickUVM vs. other UVM testbench generators

A general-purpose comparison: QuickUVM as a generator for **any digital functional
verification project**, not one protocol. Judged against the four pillars of a UVM
environment — **stimulus, checking, coverage, reuse** — plus registers and infra.

> Status: reflects QuickUVM **v0.9.2**. The capability matrix is kept in sync with the
> shipped feature set; see `parity_roadmap.md` for what is planned and in what order.

## Tools compared

- **QuickUVM** (this project) — Python/Jinja2, flat Paradigm-Works / Cliff-Cummings style.
- **Siemens UVM Framework (UVMF)** 2026.1 — Python/Jinja2; BFM-based; the design model
  for our pragma mechanism.
- **Doulos Easier UVM Code Generator** — Perl (`easier_uvm_gen.pl`); separate-include
  preservation.
- **icdk `uvmgen`** (Dragon-Git) — Python/Mako.
- **`gen_uvm`** (asicnet) — Python rewrite of Easier UVM.

## Preservation strategy (QuickUVM's headline strength)

| Tool | Mechanism | Orphaned user code | Backup |
|---|---|---|---|
| **QuickUVM** | in-file pragma fences (`// pragma quickuvm custom …`) | **fail-closed** (error unless `--allow-drop`) | rolling `<file>.bak.<N>` |
| **UVMF** | in-file pragma fences (`// \| # pragma uvmf custom …`) | fail-closed (`--merge_skip_missing_blocks` to override) | `_bak_<N>` tree |
| **Doulos Easier UVM** | user code in separate `./include/*.sv` files + factory overrides | n/a (user files never regenerated) | n/a |
| **icdk uvmgen** | none — unconditional overwrite | code lost | none |
| **gen_uvm** | none evident | code lost | none |

QuickUVM matches UVMF's fail-closed safety (validate markers → detect orphans → backup →
refuse-or-`--allow-drop`) and beats icdk/gen_uvm (which overwrite hand edits). This is
QuickUVM's most differentiated capability and the core of its identity.

## Capability matrix (general-DV view)

Legend: ✓ full · ◑ partial / skeleton-only · ✗ none · — n/a

| Dimension | QuickUVM v0.9.2 | UVMF | Doulos | icdk uvmgen | gen_uvm |
|---|---|---|---|---|---|
| **Foundations** |
| Language / templating | Python / Jinja2 | Python / Jinja2 | Perl | Python / Mako | Python |
| Config input | YAML (Pydantic-validated) | YAML (voluptuous) | `key=value` files | JSON/YAML/TOML/XML | `entity_desc.txt` (+VHDL) |
| Code-preservation safety | **fail-closed + rolling backup** | fail-closed + backup | separate files | none | none |
| Footprint | tiny, hackable (MIT) | large framework | medium | medium | small |
| **Pillar 1 — Stimulus / CRV** |
| Transaction field modeling | ◑ name+width+rand only | ✓ | ✓ | ✓ | ◑ |
| Constraints / enums / structs / var-length | ✗ | ✓ | ◑ | ◑ | ✗ |
| Sequence library (layered, reset, error-inject) | ✗ (one base seq) | ✓ | ◑ | ◑ | ◑ |
| Virtual sequencer / virtual sequences | ✗ | ✓ | ◑ | ✗ | ✗ |
| **Pillar 2 — Checking** |
| Scoreboard | ◑ single-stream, in-order | ✓ (+strategies) | ◑ | ◑ | ◑ |
| Out-of-order / multi-stream / predictor framework | ✗ | ✓ | ✗ | ✗ | ✗ |
| SVA / interface assertions | ✗ | ✓ | ◑ | ✗ | ✗ |
| Whitebox internal-signal observation (spy/probe) | ✓ (K2: opt-in XMR probe interface + monitor) | ◑ (bind conventions) | ◑ | ✗ | ✗ |
| **Pillar 3 — Coverage** |
| Functional coverage from fields | ✗ (one empty covergroup) | ◑/✓ | ◑ | ◑ | ✗ |
| Register coverage | ✗ | ✓ | ◑ | ◑ | ✗ |
| **Pillar 4 — Reuse / architecture** |
| Packaged reusable VIP (`<agent>_pkg`) | ✗ (flat monolithic `<dut>_tb_pkg`) | ✓ | ◑ | ◑ | ✗ |
| Hierarchical sub-environments | ✗ | ✓ | ◑ | ✗ | ✗ |
| Parameterized interfaces/agents | ✗ | ✓ | ◑ | ✓ | ✗ |
| Multi-agent analysis routing | ◑ per-agent (MVP) | ✓ | ◑ | ◑ | ◑ |
| **Registers** |
| Generates `uvm_reg_block` from a spec | ✗ (consumes external block) | ✓ | ✓ | ✓ (`ral_pkg`) | ✗ |
| RAL wiring: adapter / predictor / front+back door | ✓ (incl. custom frontdoor) | ✓ | ✓ | ✓ | ✗ |
| **Clocking / language** |
| Multi-clock / multi-reset / CDC | ✗ (single clk+rst) | ✓ | ◑ | ◑ | ✗ |
| Mixed-language (VHDL) / BFM / emulation | ✗ (SV interface only) | ✓ (SV+VHDL BFMs) | ✗ | ✗ | ◑ |
| **Infrastructure** |
| Run infra | ◑ `.f` filelists | ✓ per-sim makefiles + testlists | ✓ | ✓ | ✓ |
| Regression runner / coverage-merge | ✗ | ✓ | ◑ | ◑ | ◑ |
| UVM version selector (1.1d / 1.2) | ✓ | ◑ | ✗ | ✗ | ✗ |
| Ecosystem (examples, docs, support) | ◑ 1 example, MIT, single-author | ✓ vendor-backed | ✓ | ◑ | ◑ |

## Where QuickUVM stands (honest, general-DV)

QuickUVM is currently a **single-block skeleton generator + best-in-class code
preservation + RAL wiring**. It accelerates boilerplate and makes regeneration safe, but
it under-serves all four UVM pillars to varying degrees:

- **Stimulus:** transactions are a flat `name+width+rand` field list — no constraints,
  enums, structs, or variable-length payloads; no sequence library; no virtual sequences.
  Constrained-random — the heart of CRV — is essentially hand-written.
- **Checking:** single-stream, single-transaction-type, in-order scoreboard only; no
  out-of-order/multi-stream/predictor framework; no SVA scaffolding.
- **Coverage:** the weakest pillar — one empty covergroup stub; no field-derived
  coverpoints, cross-coverage, or register coverage, despite the generator already
  holding the field/register data needed to derive them.
- **Reuse:** flat monolithic package (no standalone VIP), no hierarchy, no
  parameterization — caps QuickUVM at one bench at a time.
- **Registers:** wiring only — the `uvm_reg_block` must come from an external tool
  (e.g. reggen/SystemRDL); QuickUVM does not generate it.

**Genuine strengths (generator-agnostic):** fail-closed pragma preservation with rolling
backups (matches UVMF, beats uvmgen/gen_uvm); Pydantic-validated config; RAL wiring
across front/back/custom-front-door with a UVM-version selector; a tiny, readable,
hackable MIT codebase well suited to teaching and small single-block benches.

## Suitability summary

| Project shape | Fit today |
|---|---|
| Single block, 1–2 simple interfaces, hand-written protocol logic | **Good** — fast to "compiles & runs"; preservation keeps hand edits safe |
| Register-heavy block (with an external reggen) | **OK** — RAL wiring is solid; you supply the block + adapter mapping |
| Coverage-driven closure | **Weak** — coverage model is unscaffolded |
| Multi-interface / coordinated stimulus | **Weak** — no virtual sequences |
| Parameterized / reusable VIP / block→subsystem→SoC reuse | **Not yet** — flat, non-hierarchical, non-parameterized |
| Multi-clock / CDC / mixed-language | **Not supported** |

## Notable finding from the original comparison work

Auditing QuickUVM against UVMF surfaced that the pragma feature was *advertised but
largely non-functional*: aggressive Jinja `{%-` whitespace trimming glued generated code
onto the marker lines, so the old merger could not extract most sections — and in the
monitor it silently **commented out the DUT-sampling assignments**. Both the preservation
engine and the templates were corrected and locked down with regression tests
(see `action_plan.md`, Track A).
