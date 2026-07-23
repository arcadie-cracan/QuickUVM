# QuickUVM vs. other UVM testbench generators

A general-purpose comparison: QuickUVM as a generator for **any digital functional
verification project**, not one protocol. Judged against the four pillars of a UVM
environment — **stimulus, checking, coverage, reuse** — plus registers and infra.

> Status: reflects QuickUVM **v1.1.0**. The capability matrix is kept in sync with the
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

| Dimension | QuickUVM v1.1.0 | UVMF | Doulos | icdk uvmgen | gen_uvm |
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
| Out-of-order / multi-stream / predictor framework | ✓ (A2 + K0 predictor seam; SV, or bring your own DPI library) | ✓ | ✗ | ✗ | ✗ |
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
| Run infra | ✓ (R1: `.f` filelists + a generated Makefile) | ✓ per-sim makefiles + testlists | ✓ | ✓ | ✓ |
| Regression runner / coverage-merge | ✓ (R1: `make regress` = tests × seeds + `imc` merge; Xcelium) | ✓ | ◑ | ◑ | ◑ |
| UVM version selector (1.1d / 1.2) | ✓ | ◑ | ✗ | ✗ | ✗ |
| Ecosystem (examples, docs, support) | ◑ ~29 examples (Xcelium-validated), MIT, single-author | ✓ vendor-backed | ✓ | ◑ | ◑ |

## Composition matrix (feature × feature)

The schema audit's final recommendation: publish where features **compose**, where they
are **walled**, and where they are simply **untried** — so an apparent limitation reads
as stated scope, and an untested cell reads as exactly that. Every cell below is
mechanically backed: ✅ cites a committed, Xcelium-green example; 🚫 cites a fail-closed
validator (all walls reject loudly, most with teaching errors); `·` means no example
composes the pair and no wall forbids it — untried, not broken.

The walls come in two species, worth distinguishing (the audit's framing):
**theorems** — structural impossibilities that will never lift (marked in the notes) —
and **"this slice"** scope statements, each of which names its own follow-up in the
error text.

Axes: **MA** ≥2 agents (flat) · **RE** `replicas` · **IN** `instances`/`parameters` ·
**SU** `subenvs` · **BA** boundary agents · **MC** multi-clock/reset · **IO** `inouts` ·
**RS** responder (any `respond:` shape) · **PR** `proactive` hybrid · **RR**
`request_ready` · **WI** `window` · **OO** `match: out_of_order` · **RC**
`reference_model: c` · **RM** register model (RAL) · **PB** `probes` · **VP**
`kind: vip` / `agent_refs` · **CV** rich coverage entries · **RG** `regress`

|      | RE | IN | SU | BA | MC | IO | RS | PR | RR | WI | OO | RC | RM | PB | VP | CV | RG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **MA** | 🚫 | 🚫 | · | · | ✅ | ✅ | ✅ | · | · | · | ✅ | · | ✅ | · | · | ✅ | ✅ |
| **RE** |    | 🚫ᵗ | · | 🚫 | 🚫 | 🚫 | ⚠¹ | ✅ | · | 🚫 | 🚫 | 🚫 | · | · | · | 🚫 | ✅ |
| **IN** |    |    | · | 🚫 | 🚫 | · | 🚫 | · | · | 🚫 | 🚫 | 🚫 | 🚫 | 🚫 | · | 🚫 | · |
| **SU** |    |    |    | ✅ | ⚠² | · | · | · | · | 🚫 | 🚫 | 🚫 | 🚫 | 🚫 | 🚫 | · | 🚫 |
| **BA** |    |    |    |    | · | · | 🚫 | · | · | · | · | · | · | · | · | · | · |
| **MC** |    |    |    |    |    | ✅ | ✅ | · | · | · | · | · | · | · | · | · | ✅ |
| **IO** |    |    |    |    |    |    | ✅ | · | · | · | · | · | · | · | · | ✅ | ✅ |
| **RS** |    |    |    |    |    |    |    | ✅ | ✅ | · | · | · | ⚠³ | · | · | · | ✅ |
| **PR** |    |    |    |    |    |    |    |    | ·⁴ | · | · | · | · | · | · | · | ✅ |
| **RR** |    |    |    |    |    |    |    |    |    | · | · | · | · | · | · | · | ✅ |
| **WI** |    |    |    |    |    |    |    |    |    |    | · | 🚫 | · | · | 🚫 | · | ✅ |
| **OO** |    |    |    |    |    |    |    |    |    |    |    | · | · | · | 🚫 | · | · |
| **RC** |    |    |    |    |    |    |    |    |    |    |    |    | · | · | · | · | · |
| **RM** |    |    |    |    |    |    |    |    |    |    |    |    |    | · | 🚫 | ✅ | ✅ |
| **PB** |    |    |    |    |    |    |    |    |    |    |    |    |    |    | 🚫 | · | · |
| **VP** |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    | ·⁵ | 🚫 |
| **CV** |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    | ✅ |

**Footnotes** — ᵗ theorem: identical-copies×shared-vectored-DUT vs
parameterized-variants×per-instance-DUTs; one vectored port cannot carry per-bit
widths, so the exclusion never lifts. ¹ a *pure* responder is walled; a `proactive:
true` **hybrid** composes (proven: `alert_array`). ² clocked leaves compose
(one clock per leaf); a *multi-clock leaf* is walled. ³ `register_model.bus_agent`
must not be a non-proactive responder (the sequencer-clobber trap); a hybrid is
exempt. ⁴ `proactive` + `request_ready` both require `respond: on_request`, so they
can co-exist — probe-verified during the schema audit, no committed example yet.
⁵ rich coverage entries are fence-*permitted* on a VIP (the covergroup ships in the
agent package; unit-tested) — no committed example yet.

### Proven compositions (each cell's citation)

| Cell | Example(s) |
|---|---|
| MA×MC | `cdc_fifo`, `mclk`, `mxclk` |
| MA×IO, MC×IO, IO×RS | `spi_host` (inouts + multi-clock + prefetch responder, on one bench) |
| MA×RS | `axi_slave` (two responders, one DUT), `spi_host` |
| MA×OO | `reqrsp` |
| MA×RM, MA×CV, RM×CV | `rvtimer` (2 agents + RAL + rich coverage, one bench) |
| RE×RS, RE×PR, PR×RS | `alert_array` (N proactive hybrids into one vectored DUT) |
| SU×BA | `chip` (boundary agent + composed blocks) |
| MC×RS | `spi_device`, `spi_host` (dut-driven clock responders) |
| IO×CV | `odbus` |
| RS×RR | `axi_handshake` |
| WI (+RG) | `es_adaptp` |
| RM×RG | `ahb_regs`, `rvtimer` |
| RG × nearly everything | 20 of the examples carry a `regress:` block |

### The wall annotations (what each 🚫 says, condensed)

- **replicas**: sole agent · no multi-clock · no inouts · no coverage collectors ·
  plain single-stream scoreboard only · no `language: c` · *(theorem)* no
  instances/parameters.
- **instances**: single-agent bench · no responder · no analysis customization
  (window/OoO/rich coverage) · no `language: c` · no parameterized RAL bus agent ·
  no probes · no multi-clock.
- **subenvs**: no register model (top or child) · no regress · no probes ·
  composition scoreboards are in-order two-stream SV (no window/OoO/DPI).
- **boundary agents**: no responder shape · no parameters/instances/replicas ·
  top level only.
- **`reference_model: c`**: the sole flat single-stream non-windowed scoreboard only
  (everywhere else the bypass would silently ignore it — rejected instead).
- **`kind: vip`**: ships agent packages only — every bench-layer section is fenced
  (user tests, scoreboards, bare coverage routing, probes, vseqs, regress, subenvs,
  register model).

Reading the matrix honestly: the tier-1 stimulus/checking primitives compose almost
freely (the ✅-dense upper rows and `regress` column), while the walls concentrate on
the **structure** features (replicas / instances / subenvs / vip) — the audit's
"corridor-general" finding, now stated as scope rather than discovered as surprise.
The `·` cells are the roadmap's cheapest experiments: each is one probe away from
becoming a ✅ or a wall.

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
  (K0 — SV, or a C/C++ **library** you import yourself; the generated `language: c` bridge
  is a convenience for simple scalar models, see `reference_model_seam.md`); in-interface SVA
  scaffolding + a user pragma hook (K1 — a skeleton,
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

**Still open (roadmap):** register functional coverage (V2). And, from the empirical
OpenTitan comparison ([`comparison_opentitan.md`](comparison_opentitan.md) / the maturity
assessment), two architectural gaps: no reusable/shared VIP (a fresh agent is regenerated
per bench) and no reactive/responder (device) agent — the latter now has a worked design
([`reactive_agent_investigation.md`](reactive_agent_investigation.md)), not an
implementation.

**Closure infrastructure (R1) — done, with an honest edge.** `regress:` generates a
Makefile that elaborates once and runs the derived testlist (tests + RAL + CSR) × seeds
against the snapshot, verdicts each run from the UVM severity block (`xrun` exits **0**
even on UVM_ERROR — the exit code is not a verdict), prints a reproduce command per
failure, and merges + reports coverage via `imc`. It is **Xcelium-only** by choice.
Related: verible cannot see elaboration-class defects and no free simulator closes that
gap (Verilator is blind to it; Icarus rejects clean code), so the simulator gate is split
into an enforced static check in CI plus a licence-needing `scripts/xrun_gate.sh` the
maintainer runs — see `parity_roadmap.md` § R1.

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
| Coverage-driven closure (regression + merge) | **Good** — field coverage (V1) + `make regress`: tests × seeds, merged coverage, reproducible seeds (R1, Xcelium) |
| Register functional coverage | **Not yet** — V2 planned |
| CDC checking / mixed-language (VHDL) / emulation | **Not supported** — out of scope |

## Notable finding from the original comparison work

Auditing QuickUVM against UVMF surfaced that the pragma feature was *advertised but
largely non-functional*: aggressive Jinja `{%-` whitespace trimming glued generated code
onto the marker lines, so the old merger could not extract most sections — and in the
monitor it silently **commented out the DUT-sampling assignments**. Both the preservation
engine and the templates were corrected and locked down with regression tests
(see `action_plan.md`, Track A).
