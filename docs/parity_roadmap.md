# QuickUVM parity roadmap (v0.9 → v1.0)

Goal: make QuickUVM a credible **general-purpose** UVM generator for any digital
functional-verification project — not just single-block, single-protocol benches —
while preserving its identity (simplicity + fail-closed pragma preservation).

See `comparison.md` for the current capability matrix and `code_preservation.md` for the
merge contract every phase must keep intact.

## Reprioritization note (why this differs from the v0.3 plan)

The earlier roadmap was sequenced by the needs of the SPI-bridge bring-up, so it pursued
the **register model (RAL) first**. That work shipped (C4a/b/c), but it is *not* the
highest-leverage gap for general DV. Judged across arbitrary DUTs against the four UVM
pillars — **stimulus, checking, coverage, reuse** — QuickUVM is weakest where it matters
most universally:

- **Coverage** is the weakest pillar and the deliverable of coverage-driven verification,
  yet it is essentially unscaffolded (one empty covergroup).
- **Stimulus** modeling is too primitive for real protocols (flat `name+width+rand`
  fields; no constraints; one base sequence; no virtual sequences).

A third lever comes from MathWorks HDL Verifier (which UVMF/Easier UVM lack): it
generates the **reference model / scoreboard checker** from an executable spec and bridges
it into the SV scoreboard via **DPI-C**. The hand-written predictor is the biggest
effort sink in a real bench (cf. the SPI bridge's `sb_calc_exp`), so a generated
**predictor seam** (bring-your-own golden model over DPI-C) is high-leverage too.

So this revision leads with **stimulus richness + coverage + a reference-model seam**,
then **reuse**, then **checking generality** and **infra/clocking**. RAL block
*generation* is intentionally left to external tools (reggen/SystemRDL); QuickUVM owns
the *wiring*, which is done.

## What's already shipped (v0.4 → v0.9)

| Phase | Result | Version |
|---|---|---|
| Pragma preservation hardening (Track A) | fail-closed merge + rolling backups; latent `{%-` defect fixed | — |
| F1 — Config objects + `uvm_config_db` | `<agent>_config`/`env_config`; `is_active` wired | v0.3.0 |
| C1 — Analysis fabric (MVP per-agent routing) | opt-in `analysis:` (coverage list + scoreboards) | v0.4.0 |
| C4a — RAL front-door wiring | adapter skeleton + build/lock/predictor + `reg_test` | v0.5.0 |
| C4b — RAL backdoor | `backdoor_root` → `add_hdl_path`; backdoor `reg_test` | v0.6.0 |
| UVM version selector | `project.uvm_version: 1.1d \| 1.2` | v0.7.0 |
| C4c — Custom `uvm_reg_frontdoor` | generated skeleton + `set_frontdoor` | v0.8.0 |
| Scoreboard `sb_enable` / `sb_flush` | disable on reg tests; configurable startup flush | v0.9.x |

These stay as-is. The register pillar (wiring) is considered **done**; block generation
is delegated to reggen.

## Identity constraints (every phase)

- **Opt-in & byte-identical when unused.** New config blocks must leave existing output
  unchanged when omitted (as C1/C4 already do). Simplicity for small benches is the brand.
- **Fail-closed preservation preserved.** Extend the marker-regression suite to each new
  config shape (rich transactions, params, vseqs, subenvs).
- **Skeleton, not magic.** Generated logic that can't be inferred stays in pragma regions
  — but the *default skeleton must encode good patterns* (see X0).

## X0 — Template-default hardening (cross-cutting, do first; low cost)

Independent of new features: the default driver/monitor skeletons currently propagate
anti-patterns into every generated TB (observed in the field):

- driver does `@vif.cb1` with **no reset wait** → can drive during reset;
- monitor uses a **blind fixed-count sampling loop** with no frame/envelope bounding or
  malformed-input handling.

Fix the template defaults (reset-gated driver start; envelope-bounded, self-resyncing
monitor sampling) so generated benches start correct-by-construction. Cheap, high value,
no schema change.

## Priority tier 1 — the universal pillars (general-DV leverage)

### S1 — Rich transaction / constraint modeling  *(highest leverage; stimulus)*
Extend `PortConfig`/transaction schema beyond `name+width+rand`:
- typed fields (enum, struct, packed arrays, **variable-length payloads**);
- per-field `constraint` expressions and soft/dist constraints;
- field-level `rand`/`rand_mode` and inter-field relations.
Emit `rand` fields + `constraint` blocks + `uvm_field` automation. Without this, CRV —
the core of modern DV — is hand-written for every project.
**Accept:** a packet-style transaction (header + var-length payload + CRC) with
constraints generates and randomizes.

### V1 — Functional coverage from fields  *(highest leverage; coverage)*
Derive a real covergroup from the transaction/config fields the generator already has:
config-driven coverpoints + bins, optional crosses, sampled from the monitor's analysis
write. Opt-in `coverage_model:` block; default stays the empty stub.
**Accept:** coverpoints/bins for a transaction's fields generate and accumulate.

### S2 — Sequence library
Generate more than one base sequence: a small library (incrementing/random/directed),
reset and error-injection sequence skeletons, and a sequence-of-sequences. Config-driven
test → sequence selection (replace the bare `num_items`).
**Accept:** a test selects from ≥2 generated sequences + a reset sequence.

### C2 — Virtual sequencer + virtual sequences
`env_vsqr` (agent sequencer handles) + `env_vseq_base`; tests run vseqs. Required for any
multi-interface DUT (i.e. most DUTs).
**Accept:** a vseq coordinating ≥2 agents.

### K0 — Reference-model / DPI-C predictor seam  *(checker; inspired by HDL Verifier)*
The scoreboard predictor is the biggest hand-written-effort sink in a real bench, and
UVMF/Easier UVM leave it entirely to the user. Rather than synthesize a predictor,
generate the **seam** so a golden model drops in:
- a defined predictor interface — a `uvm_component` with one `predict(req) → exp` method —
  so the scoreboard is checker-agnostic (replaces today's ad-hoc `sb_calc_exp` blob);
- optional **DPI-C scaffolding** (`import "DPI-C"` decls + a C/C++ header & stub whose
  signature is derived from the transaction fields) so the golden model can be written in
  C/C++ instead of SystemVerilog, then called per transaction;
- the scoreboard wiring that routes the monitored transaction through the predictor.

The reference-model *body* stays user code (SV or C); QuickUVM owns the interface + bridge.
This is the lever HDL Verifier exploits, minus the MATLAB/Simulink front-end (out of scope).
**Accept:** a transaction round-trips through a DPI-C golden-model stub into the scoreboard.

## Priority tier 2 — reuse / architecture

### F2 — VIP package restructuring
`layout: flat | packaged`. `packaged`: standalone `<agent>_pkg`, `<env>_pkg`, thin bench,
per-package `.f`. Unlocks separate compilation, versioning, and cross-project reuse.
**Accept:** `<agent>_pkg` compiles standalone; `layout: flat` stays byte-identical.

### C3 — Parameterization
`parameters:` at interface/agent/env/bench; param refs in field widths; `#(...)` threaded
via Jinja macros.
**Accept:** one agent reused at two widths.

### H1 — Sub-environments
`subenvs:`; nest child env packages + configs + param propagation. Depends F1/F2/C1/C3.
**Accept:** a subsystem env composes ≥2 block envs.

## Priority tier 3 — checking generality

### A2 — Scoreboard / comparison-strategy library
Builds on the K0 predictor seam: in-order (today) **plus** out-of-order, latency-windowed,
and multi-stream comparators; "A drives → predictor → scoreboard ← B monitors" topologies
and multi-transaction-type scoreboards (the full fabric C1 deferred). K0 supplies the
swappable predictor; A2 supplies the comparison strategies around it.
**Accept:** an out-of-order scoreboard matches a reordering DUT model.

### K1 — Assertion / protocol-checker scaffolding
Generate an interface assertion module + SVA hook pragmas (protocol properties are user
code, but the binding/structure is scaffolded).
**Accept:** an `*_if` emits a bound checker module with a sample property.

## Priority tier 4 — clocking & infrastructure

### M1 — Multi-clock / multi-reset
Promote `clock`/`reset` to lists; per-agent clock association; multiple clock-gens + reset
generators. Needed for CDC and most real SoC blocks.
**Accept:** a 2-clock-domain bench generates and runs.

### R1 — Regression & coverage infrastructure
Per-simulator makefiles, a testlist/regression runner, seed management, and a
coverage-merge flow (coverage closure needs all of these).
**Accept:** `make regress` runs N tests × M seeds and merges coverage.

## Out of scope / low ROI (revisit only on demand)

- **V2 — Register functional coverage** (auto reg/field coverage models) — valuable but
  pairs with external reggen; do only when a register-heavy project needs closure.
- **A1 — QVIP / external-VIP integration** — niche.
- **Mixed-language (VHDL) / BFM / emulation** — large effort, narrow audience; UVMF's
  domain.
- **RAL block generation** — delegated to reggen/SystemRDL by design.

## Suggested sequencing

```
X0 template-default hardening (do first, cheap)
  │
tier 1 (universal pillars):  S1 ─┬─ V1 ─┬─ S2 ─ C2 ─ K0
                                 │       │                │
tier 2 (reuse):            F2 ─ C3 ─ H1  │                │
tier 3 (checking):              A2 ◄──────────────────────┘ (A2 builds on K0) ─ K1
tier 4 (infra):                 M1 ─ R1
```

## Parity tiers / outcome

| Tier | Phases | Result |
|---|---|---|
| **General-DV MVP (recommended)** | X0 + S1 + V1 + S2 + C2 + K0 | real CRV stimulus, field-derived coverage, multi-agent coordination, a checker seam (golden model in SV/DPI-C) |
| Reuse parity | + F2 + C3 + H1 | packaged, parameterized, hierarchical VIP |
| Checking/infra parity | + A2 + K1 + M1 + R1 | multi-stream checking, assertions, multi-clock, regression |

The General-DV MVP now closes the loop on all three things that make a generated bench
actually *do* verification rather than just compile: **stimulus in** (S1/S2/C2),
**coverage observing** (V1), and a **golden model checking** (K0).

Recommendation: do **X0** immediately (cheap correctness win), then pursue the
**General-DV MVP** (stimulus + coverage + virtual sequences + reference-model seam) —
these are the pillars that bite *every* project. Defer reuse/hierarchy/infra until a
multi-block or closure-driven need forces them. QuickUVM's niche remains simplicity +
best-in-class code preservation.
