# QuickUVM maturity assessment — empirical `rv_timer` reproduce-and-compare

An **empirical** maturity assessment of QuickUVM against a mature industrial UVM
verification environment. Where [`comparison_opentitan.md`](comparison_opentitan.md)
maps QuickUVM's output against OpenTitan's `rv_timer` DV *on paper*, this document
**builds** an equivalent single-block bench with QuickUVM, fills the functional
code, and runs it **green on Xcelium (25.09)** — turning "close match" (a claim)
into "runs and checks" (a demonstration), and measuring the split between
tool-generated and human-written code.

Reproduced bench: [`examples/rvtimer/`](../examples/rvtimer/) — an `rv_timer`-equivalent
timer block (register file + counter + interrupt), 4 tests, **0 UVM_WARNING/ERROR/FATAL**.

## Executive summary — three verdicts

- **Generation parity: STRONG (proven).** For a real register-block DV environment,
  QuickUVM auto-generated the entire structure — two agents, env, RAL wiring, the C5
  CSR test suite, the scoreboard/predictor seam, config-driven coverage, `tb_top`,
  and filelists — that runs and checks on Xcelium. **~873 lines of DV code were
  generated; ~42 lines of DV logic were hand-written** (the golden model, the
  adapter body, the directed interrupt test, the driver/monitor sample seams), plus
  a 56-line RAL (a reggen stand-in) and the 61-line DUT. "Generate flat" demonstrably
  replaces "inherit framework" for this class of block.
- **Architecture / reuse: the honest weak flank.** QuickUVM regenerates a fresh
  agent per bench (no shared/vendored VIP) and has no reactive/responder (device)
  agent — the interrupt line is modelled as a monitored output. Partly offset by the
  deliberate no-base-class stance (the whole bench is inspectable, dependency-free).
- **Closure infrastructure: the actionable roadmap.** No regression runner / seed
  management / coverage merge (R1), no register functional coverage from the RAL
  (V2), no testplan. The build made R1's absence concrete: the four tests were run
  one `+UVM_TESTNAME` at a time, by hand.

**Headline finding — why building beats paper analysis.** The empirical build
surfaced (and this work fixed) a **latent generator bug** that the on-paper analysis
and the verible-only CI both missed: the explicit `analysis.coverage:` path emitted
`<agent>_cov <agent>_cov;` (a coverage member named identically to its type), which
verible accepts but **Xcelium rejects at elaboration** (`<agent>_cov::type_id`
resolves the variable, not the type). No committed example exercised that path, so it
had never been elaborated. Fixed by renaming the member to `<agent>_cov_h`
(byte-identical for all 26 existing examples; the first bench to use the path is this
one). This is itself evidence for two roadmap items: **Xcelium-in-CI** (R1) and a
regression bench that exercises the coverage path.

## Method & fairness (stated before any numbers)

Two structural asymmetries are normalized up front so the verdict is credible.

**1. TL-UL → generic APB-style register bus.** OpenTitan uses TileLink; we hold the
register bus generic (single-cycle, `examples/regfile/`-style). The thing under test
is *how much of the DV environment the tool generates* — env, RAL wiring, adapter
seam, predictor/scoreboard seam, CSR suite, coverage, vseqs — **none of which are
TL-UL-specific**. TL-UL enters only at the adapter's `reg2bus`/`bus2reg` (user code
in both worlds). TL-UL's protocol machinery (integrity, `tl_errors`, outstanding
requests) is a VIP concern, out of QuickUVM's generic scope, and is scored separately
as an explicit **non-goal**, not folded into the maturity verdict.

**2. Inherit (~6×) vs generate (flat) → four LOC buckets, never one number.**
OpenTitan's `rv_timer` is ~1,492 hand-written per-IP lines riding on ~8,500+ inherited
`cip_lib`/`dv_base` lines (≈1:6), of which only ~900 (the 380-line scoreboard timing
model + ~520 lines of directed vseqs) is truly DUT-specific. We count QuickUVM's
buckets separately; QuickUVM's bucket (A) is **mechanically countable** — grep the
pragma-delimited regions of the frozen example — which is itself a methodological
advantage (how much the human wrote is a measured quantity, not an estimate).

## The reproduced bench + Xcelium evidence

`examples/rvtimer/`: a `host` register-bus agent + a passive `irq` interrupt agent, a
5-register hand-written `uvm_reg_block` (4 R/W config + 1 RO `INTR_STATE`, backdoor
slices), the C5 CSR suite, a golden-model data-path scoreboard, K1 SVA on `intr`, and
config-driven coverage. All four tests pass with **0 UVM_WARNING/ERROR/FATAL on
Xcelium 25.09**:

| Test | What it exercises | Result |
|---|---|---|
| `rand_test` | random register traffic (golden-model data-path scoreboard) **+** a directed RAL sequence that arms the timer and verifies the interrupt asserts then clears | 0/0/0 |
| `rvtimer_csr_hw_reset_test` | C5 `uvm_reg_hw_reset_seq` — reset values | 0/0/0 |
| `rvtimer_csr_bit_bash_test` | C5 `uvm_reg_bit_bash_seq` — per-bit R/W | 0/0/0 |
| `rvtimer_csr_rw_test` | C5 `uvm_reg_access_seq` — front-door vs **backdoor** (via `backdoor_root`) | 0/0/0 |

verible-lint clean; the committed `gen/` regenerates byte-for-byte (byte-identity gate).

## Effort measurement (four buckets, counted from the built bench)

| Bucket | QuickUVM (`rvtimer`) | OpenTitan (`rv_timer`) |
|---|---|---|
| **(A) Human-authored, DUT-specific DV** | **~42 lines** of filled pragma logic: golden-model `predict()` (6), adapter `reg2bus`/`bus2reg` (7), directed timer-interrupt test (23), monitor combinational-read re-sample (3), driver read-data sample (3) | ~900 lines: 380-line scoreboard timing model + ~520 lines directed vseqs |
| **(B) Human-authored boilerplate** | ~0 (generated) | ~280 (env/cfg/pkg/tb parameterizing base classes) |
| **(RAL)** | 56 lines hand-written `uvm_reg_block` (a **reggen stand-in**; a real flow generates it) | reggen-generated from `.hjson` |
| **(DUT)** | 61 lines RTL (the design — present in both worlds) | the RTL block |
| **(D) Machine-carried DV** | **~873 lines generated** across 35 files (+ 2 filelists), no base-class dependency | ~8,500+ inherited `cip_lib`/`dv_base` + reggen RAL |

Reading: bucket (A) is the effort a verification engineer actually spends, and it is
directly comparable. QuickUVM's ~42 lines is smaller than OpenTitan's ~900 **because
this bench is smaller in checking scope** (one directed interrupt test + a data-path
scoreboard vs a full cycle-accurate timing model + a large directed vseq library) —
the fair reading is *not* "10× less work" but "the irreducible hand-written DV
(golden model + directed stimulus + adapter body) is the same shape in both, and
QuickUVM adds no boilerplate tax on top of it." Bucket (D) is the architectural axis:
OpenTitan carries ~8,500 lines by inheritance (a shared, battle-tested asset you never
read); QuickUVM carries ~873 by generation (a per-bench, inspectable, base-class-free
artifact). Different distributions of the same total — not a raw-LOC winner.

## Component-by-component scorecard (from the *built* bench)

Level: **AUTO** (generated, runs, no fill) / **SKELETON** (generated seam + bounded
pragma fill) / **HAND** (human writes it) / **ABSENT**. OT mechanism: `INHERIT`
(cip_lib/dv_base), `REGGEN`, or `HAND`.

| # | Dimension | QuickUVM | OT mech | Evidence in the built bench |
|---|---|---|---|---|
| 1 | Env / agent architecture | **AUTO** | INHERIT | `rvtimer_env.svh`, both agents generated; runs 0/0/0 |
| 2 | RAL wiring (build/lock/adapter/predictor/backdoor) | **AUTO** (wiring) + **SKELETON** (adapter body 7 ln) | INHERIT+REGGEN | `add_hdl_path`, `set_sequencer`, `uvm_reg_predictor` all generated |
| 3 | CSR test suite (hw_reset/bit_bash/rw) | **AUTO** | INHERIT (csr_utils) | 3 CSR tests pass on Xcelium incl. backdoor `rw` |
| 4 | Stimulus (CRV: enums/structs/arrays/constraints) | **AUTO** | HAND | S1 (host transaction) |
| 5 | Functional coverage (coverpoints/bins/cross) | **SKELETON** (config-driven) | HAND (env_cov) | `host_cov` from `coverage_models:` — addr bins + wr + cross |
| 5b | **Register coverage from RAL** | **ABSENT** | REGGEN | V2 gap — reg/field covergroups not derived from the RAL |
| 6 | Checking / scoreboard | **SKELETON** (seam) + **HAND** (golden 6 ln) | HAND+INHERIT | golden shadow `predict()` + generated comparator; data-path 0/0/0 |
| 7 | Sequences / virtual sequences | **AUTO** + **SKELETON** | INHERIT+HAND | S2/C2; directed timer vseq hand-written (23 ln) |
| 8 | **Reuse / shared VIP** | **ABSENT** | INHERIT (tl_agent) | the host agent (+ its read-sample driver seam) is regenerated per bench |
| 9 | **Reactive / responder (device) agent** | **ABSENT** | INHERIT | `intr` modelled as a monitored output, not driven by a device agent |
| 10 | Multi-clock / multi-reset | **AUTO** | INHERIT | M1 (not needed here; single clock) |
| 11 | Assertions (in-interface SVA) | **SKELETON** | HAND (binds) | K1 — `a_intr_known` on `irq_if` |
| 12 | **Regression / coverage-closure infra** | **ABSENT** | INHERIT (dvsim) | R1 — tests run one `+UVM_TESTNAME` at a time, by hand |
| 13 | **Testplan (traceability)** | **ABSENT** | HAND (testplan.hjson) | no plan-to-coverage mapping |
| 14 | CSR-test **register exclusions** | **HAND** (UVM resource in RAL) | HAND (csr_excl) | had to set `NO_REG_ACCESS_TEST` on RO `intr_state` — no config knob |
| 15 | Code preservation / regeneration | **AUTO (best-in-class)** | n/a | every hand-filled pragma survived regeneration; byte-identity gate |
| 16 | No base-class dependency | **AUTO (flat)** | opposite | the whole bench compiles with only `uvm_pkg` |
| 17 | Learnability / bring-up | **high** (a ~90-line YAML → a running, checked block bench) | must learn cip_lib | the course-integration thesis |

## The three verdicts, argued

**Generation parity — strong, and now proven.** Every structural component of a real
register-block DV env came out generated and *ran*: the agents, env, RAL wiring, CSR
suite, scoreboard seam, coverage, and `tb_top` (which auto-wired both interfaces + the
DUT + the reset generator). The human wrote the irreducible DV logic — a golden model,
an adapter body, a directed test — and nothing else. On paper this was "close match";
built, it is a green bench. This is the central maturity claim, and it holds.

**Architecture / reuse — the acknowledged gap, made concrete.** Two frictions showed
up in the build. (a) The driver's register-**read** protocol (sample the combinational
`rdata` back into the item) is a per-bench pragma fill — a shared bus VIP would provide
it once; regenerating it per bench is the "no reusable VIP" gap in miniature. (b) The
interrupt is a monitored output; a true reactive/responder agent (to *drive* protocol
responses) does not exist. Both are correctly on the roadmap as architectural, larger-
effort items; neither blocks single-block work.

**Closure infrastructure — the roadmap the build wrote for us.** R1's absence was not
abstract: there is no `make regress` to run the four tests × seeds and merge coverage —
we invoked `xrun` four times by hand. V2 (register coverage from the RAL) would have
sampled `INTR_STATE`/config-field coverage for free; instead coverage is hand-specified.
And the CSR suite has **no exclusion knob** (#14): a hardware-set RO register trips
`uvm_reg_access_seq`, and the fix was a manual UVM resource in the RAL — OpenTitan
expresses this declaratively via `csr_excl`/reggen `swaccess`.

## Differentiators (why "generate flat" is legitimate, not merely lesser)

- **Byte-identity + pragma preservation.** Every one of the ~42 hand-filled DV lines
  lives in a fenced pragma region and **survived regeneration** unchanged (verified by
  the byte-identity gate). "How much did the human write" is therefore a *measured*
  quantity — the whole effort table above is `grep`-derived, not estimated.
- **No base-class dependency.** The bench compiles against `uvm_pkg` alone — no
  `cip_lib`/`dv_base` to vendor, learn, or track. The full env is ~873 inspectable
  lines, not a 6-level inheritance chain.
- **Learnability.** A ~90-line YAML plus ~42 lines of DV glue produced a running,
  self-checking register-block bench with a CSR suite. That low barrier is the
  course-integration thesis (see [`integrare-curs-verificare.md`], untracked): a
  student reaches a green, checked bench without first mastering an industrial
  framework.

## Prioritized action list (feeding `parity_roadmap.md`)

Ordered by leverage × tractability, **confirmed against the built bench**:

1. **R1 — regression & coverage-closure infra** (`make regress`, seed management,
   coverage merge). The sole remaining roadmap item; the build made its absence
   concrete. **Highest priority, most tractable.** Pair with **Xcelium-in-CI**, which
   would have caught the coverage-collision bug this assessment fixed.
2. **V2 — register functional coverage from the RAL** — reg/field covergroups sampled
   by the predictor. `rvtimer` proves the need (coverage of `INTR_STATE`/config fields
   is hand-written today).
3. **CSR-test register exclusions** (a `csr_excl`-equivalent config knob) — small,
   high-credibility; today a hardware-RO register needs a manual UVM resource.
4. **Testplan generation** (traceability / plan-to-coverage) — ABSENT; low-effort.
5. **Reusable / shared VIP** (a vendored bus agent beyond F2's packaged layout) — the
   biggest architectural gap; the driver read-seam refill made it concrete.
6. **Reactive / responder (device) agent** — needed before UART/I2C-class blocks;
   larger effort, narrower payoff.

Items 1–4 are near-term/tractable; 5–6 are architectural/deferred — consistent with the
roadmap's existing tiering.

## Threats to validity

- **Single block, single class.** `rv_timer` is a register file + a timer + an
  interrupt — QuickUVM's stated sweet spot. A protocol-heavy block (UART/I2C) would
  score more "ABSENT" rows (reactive agent, protocol checking) that reflect *deliberate
  non-goals*, not maturity gaps. This assessment does not claim UART-class parity.
- **Generic bus, not TL-UL.** By design (see Fairness §1); the TL-UL delta (integrity,
  `tl_errors`, outstanding-request modeling) is real and out of scope, not a penalty.
- **Hand-written RAL, not reggen.** A 56-line stand-in for reggen output; faithful to
  QuickUVM's consume-by-name design but not a full reggen flow.
- **Checking scope smaller than `rv_timer`.** One directed interrupt test + a data-path
  scoreboard, not a cycle-accurate timing model — so bucket-(A) LOC understates a
  full-fidelity reproduction.

## Reference

- Built bench: [`examples/rvtimer/`](../examples/rvtimer/) (Xcelium 25.09, 0/0/0).
- On-paper companion: [`comparison_opentitan.md`](comparison_opentitan.md).
- Roadmap: [`parity_roadmap.md`](parity_roadmap.md) (R1, V2, and the items above).
- OpenTitan `rv_timer` DV (Apache-2.0): `hw/ip/rv_timer/dv/`, `hw/dv/sv/{cip_lib,dv_lib,csr_utils}`.
