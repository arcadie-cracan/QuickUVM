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
| Transaction field modeling | ✓ (S1: enums/structs/packed+dynamic arrays) | ✓ | ✓ | ✓ | ◑ |
| Constraints / enums / structs / var-length | ✓ (S1: per-field + transaction constraints) | ✓ | ◑ | ◑ | ✗ |
| Sequence library (layered, reset, error-inject) | ✓ (S2: random/incr/directed/reset/error/nested) | ✓ | ◑ | ◑ | ◑ |
| Virtual sequencer / virtual sequences | ✓ (C2: auto vsqr+vseq for ≥2 agents) | ✓ | ◑ | ✗ | ✗ |
| **Pillar 2 — Checking** |
| Scoreboard | ✓ (A2: +out-of-order, latency, multi-transaction-type) | ✓ (+strategies) | ◑ | ◑ | ◑ |
| Out-of-order / multi-stream / predictor framework | ✓ (A2 + K0 predictor seam, SV or DPI-C) | ✓ | ✗ | ✗ | ✗ |
| SVA / interface assertions | ◑ (K1: in-interface SVA scaffold + pragma hook) | ✓ | ◑ | ✗ | ✗ |
| Whitebox internal-signal observation (spy/probe) | ✓ (K2: opt-in XMR probe interface + monitor) | ◑ (bind conventions) | ◑ | ✗ | ✗ |
| **Pillar 3 — Coverage** |
| Functional coverage from fields | ✓ (V1: coverpoints/bins/cross/illegal/ignore/transition/goal) | ◑/✓ | ◑ | ◑ | ✗ |
| Register coverage | ✗ (V2 planned) | ✓ | ◑ | ◑ | ✗ |
| **Pillar 4 — Reuse / architecture** |
| Packaged reusable VIP (`<agent>_pkg`) | ✓ (F2: flat default OR packaged per-agent) | ✓ | ◑ | ◑ | ✗ |
| Hierarchical sub-environments | ✓ (H1: nested + cross-block scoreboards) | ✓ | ◑ | ✗ | ✗ |
| Parameterized interfaces/agents | ✓ (C3: + multi-instantiation at N widths) | ✓ | ◑ | ✓ | ✗ |
| Multi-agent analysis routing | ✓ (per-agent coverage + multi-scoreboard) | ✓ | ◑ | ◑ | ◑ |
| **Registers** |
| Generates `uvm_reg_block` from a spec | ✗ (by design — consumes external reggen/SystemRDL) | ✓ | ✓ | ✓ (`ral_pkg`) | ✗ |
| RAL wiring: adapter / predictor / front+back door | ✓ (+ C5 CSR suite: rw/bit_bash/hw_reset/mem_walk) | ✓ | ✓ | ✓ | ✗ |
| **Clocking / language** |
| Multi-clock / multi-reset / CDC | ✓ (M1: multi-clock/reset, mixed-unit; CDC *checking* out of scope) | ✓ | ◑ | ◑ | ✗ |
| Mixed-language (VHDL) / BFM / emulation | ✗ (SV interface only) | ✓ (SV+VHDL BFMs) | ✗ | ✗ | ◑ |
| **Infrastructure** |
| Run infra | ◑ `.f` filelists (R1: makefiles/testlists planned) | ✓ per-sim makefiles + testlists | ✓ | ✓ | ✓ |
| Regression runner / coverage-merge | ✗ (R1 planned) | ✓ | ◑ | ◑ | ◑ |
| UVM version selector (1.1d / 1.2) | ✓ | ◑ | ✗ | ✗ | ✗ |
| Ecosystem (examples, docs, support) | ◑ ~29 examples (Xcelium-validated), MIT, single-author | ✓ vendor-backed | ✓ | ◑ | ◑ |

## Where QuickUVM stands (honest, general-DV)

QuickUVM is a **single-block / subsystem UVM generator** that now covers all four pillars
for its target scope — constrained-random stimulus, field-derived coverage, multi-stream
checking, hierarchy + parameterization, multi-clock, RAL + CSR tests, assertion
scaffolding, and whitebox observation — while keeping **best-in-class code preservation**
(fail-closed pragma fences + rolling backups) and a **byte-identity discipline** (every
opt-in feature leaves unused output unchanged). Every shipped example runs green on
Xcelium, guarded by a byte-identity gate.

- **Stimulus (✓):** rich transactions — enums, structs, packed + dynamic arrays, per-field
  and transaction constraints (S1); a sequence library (random/incrementing/directed/
  reset/error/nested — S2); a virtual sequencer + virtual sequences, auto-scaffolded for
  ≥2 agents (C2).
- **Checking (✓; ◑ SVA):** two-stream scoreboards with in-order / out-of-order / latency-
  windowed / multi-transaction-type strategies (A2) over a swappable reference-model seam
  (SV or DPI-C — K0); in-interface SVA scaffolding + a user pragma hook (K1 — a skeleton,
  not a full assertion library); whitebox probe observation of internal signals (K2).
- **Coverage (◑):** config-driven functional coverage from fields — coverpoints, named
  bins, crosses, illegal/ignore/transition bins, a goal (V1). Register functional coverage
  from the RAL is not yet derived (V2, planned).
- **Reuse (✓):** a packaged per-agent VIP or a flat package (F2); parameterized interfaces/
  agents + multi-instantiation at several widths in one bench (C3); hierarchical
  sub-environments with block reuse, auto-namespacing, and cross-block scoreboards (H1).
- **Clocking (✓):** multiple clock/reset domains, mixed-unit timescale, clocked-subenv
  composition, agent-driven resets (M1). CDC *checking* and mixed-language are out of scope.
- **Registers (✓ wiring):** front/back/custom-front-door RAL wiring + the CSR test suite
  (rw / bit_bash / hw_reset / mem_walk — C5). The `uvm_reg_block` itself is consumed from an
  external tool (reggen/SystemRDL) **by design** — QuickUVM does not generate it.

**Still open (roadmap):** register functional coverage (V2); regression & coverage-closure
infrastructure — `make regress`, seed management, coverage merge (R1, the sole remaining
v1.0 item). And, from the empirical OpenTitan comparison
([`comparison_opentitan.md`](comparison_opentitan.md) / the maturity assessment), two
architectural gaps: no reusable/shared VIP (a fresh agent is regenerated per bench) and no
reactive/responder (device) agent.

**Headline strength (generator-agnostic):** fail-closed pragma preservation with rolling
backups (matches UVMF, beats uvmgen/gen_uvm); a byte-identity gate; Pydantic-validated
config; a tiny, readable, hackable MIT codebase well suited to teaching **and** to
production single-block / subsystem benches.

## Suitability summary

| Project shape | Fit today |
|---|---|
| Single block, 1–2 interfaces + a golden model | **Strong** — full stimulus/coverage/checking; fast to a green, self-checking bench |
| Register-heavy block (with an external reggen) | **Good** — RAL wiring + the CSR test suite; you supply the block + adapter mapping |
| Multi-interface / coordinated stimulus | **Good** — virtual sequencer + virtual sequences (C2) |
| Parameterized / reusable VIP / block→subsystem reuse | **Good** — packaged VIP (F2), parameterization + multi-instance (C3), hierarchy (H1) |
| Multi-clock / multi-reset | **Good** — multiple domains, mixed-unit, clocked-subenv (M1) |
| Whitebox coverage/checking of internal state | **Good** — opt-in probes (K2) |
| Coverage-driven closure (regression + merge) | **Partial** — field coverage yes (V1); no regression runner / coverage merge (R1) |
| Register functional coverage | **Not yet** — V2 planned |
| CDC checking / mixed-language (VHDL) / emulation | **Not supported** — out of scope |

## Notable finding from the original comparison work

Auditing QuickUVM against UVMF surfaced that the pragma feature was *advertised but
largely non-functional*: aggressive Jinja `{%-` whitespace trimming glued generated code
onto the marker lines, so the old merger could not extract most sections — and in the
monitor it silently **commented out the DUT-sampling assignments**. Both the preservation
engine and the templates were corrected and locked down with regression tests
(see `action_plan.md`, Track A).
