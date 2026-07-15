# T3 — OpenTitan `tl_agent` — assessment

**The question, exactly as the campaign framed it:** *can QuickUVM emit a standalone, versioned,
bench-independent VIP that a **second** generated bench consumes **by reference** rather than by
regeneration?* This is the cheapest experiment that settles whether F2 (`layout: packaged`) is
**real reuse or tidy foldering**.

**This is a finding, not a build.** The campaign's core question is settled by construction; the
PASS bar (a *generated* versioned VIP consumed by *generated* benches, with a self-test) needs a
~5–7 day generator feature that is scoped here but **not implemented** — a deliberate decision to
bank the finding and move on. Every claim below is tagged **[C]** (verified by construction, on
Xcelium) or **[I]** (inspection of the code) or **[P]** (predicted, not run).

---

## 1. The verdict

**F2 is a genuinely reusable *artefact* with no *ownership model*. In the campaign's binary — "real
reuse or tidy foldering" — it is tidy foldering, but the nuance matters and is stated here so it is
not overclaimed in either direction.**

- **[C] The standalone package is real.** `layout: packaged` emits `<agent>_pkg.sv` that imports
  only `uvm_pkg`, plus its own filelist `<agent>_pkg.f` that compiles alone. That is genuine
  separate compilation, not a naming trick. The package header even says "Reusable across projects."
- **[C] But there is no consume-by-reference path.** A second bench cannot wire in an agent it only
  imports: a config with `agents: []` is **rejected** ("at least one agent must be defined"), and
  declaring the agent **regenerates** it — two benches produce **byte-identical copies** in two
  `gen/` directories, not one shared VIP. `AgentConfig` has no `external`/`reference`/`version`
  field; `imports:` imports package *names* and wires nothing; `agents:` wires and regenerates.
  The two mechanisms that would combine into "generate once, consume by reference" never meet.

So the reuse is real where you *compile files*, and absent where the *generator owns them*.

---

## 2. Stage 0 — the seam is achievable; the gap is purely generator-side

The decisive experiment ([`t3_stage0_probe/`](t3_stage0_probe/), reproducible on Xcelium). Two
**hand-written** benches consume **one** QuickUVM-generated agent package by reference:

- **[C] M1 — edit once, both see it.** A version tag added to the *one* `io_pkg.sv` (v1→v2)
  appears in **both** benches without touching them ⇒ they compile from the shared source.
- **[C] M2 — delete it, both die.** Removing the *one* `io_pkg.sv` makes **both** benches fail to
  elaborate ⇒ they depend on one shared artefact, not private copies.

**This settles the verdict: the ownership seam is achievable with today's output shape.** Two
benches genuinely share one VIP. The only thing missing is that the *generator will not emit those
consumers* — there is no schema way to say "wire in agent `io` from package `io_pkg`, do not
regenerate it." The hand-written consumers stand in for what a `reference:` key would generate.

**[C] One concrete gotcha, found by running it:** the generated `io_pkg.f` lists its sources
relative to its own `gen/`, so a consumer in another directory must chain it with Cadence **`-F`**
(resolves relative to the file), not **`-f`** (relative to CWD). With `-f`, elaboration fails
`*SE,FILEMIS`. Reasoning would have missed this; the build caught it in one run. Stage 1 must emit
the `-F` form (or absolute paths).

---

## 3. The exact gap vs the PASS bar

| # | PASS-bar element | Have it? | Evidence |
|---|---|---|---|
| a | Version / identity on the VIP | **no** | **[C]** `ProjectMeta` has `name/author/year/uvm_version/imports` — no `version` |
| b | Generate-once / consume-by-reference | **no** | **[C]** `agents: []` rejected; declaring regenerates → byte-identical copies (§1) |
| c | VIP self-test bench (agent-to-agent, no DUT) | **no** | **[C]** `dut:` is a required field — every generated bench targets a DUT |
| d | Manifest (identity + version + depend edges) | **partial, wrong kind** | **[C]** emits `.f` filelists (relative paths, `-f` chaining); no identity/version/depend-by-name |
| e | Adapter inside the VIP | **inverted** | **[I]** `RegisterModelConfig` generates the adapter in the *env* layer (C5, per-bench); tl_reg_adapter ships *inside* `tl_agent` |

**Secondary — the multi-outstanding pipelined responder: [I/P] absent.** `respond:` has three
shapes (`on_request`, `prefetch`, `combinational`), all single-in-flight and in-order. TL-UL's
device driver holds N outstanding requests and responds out of order, correlated by source id.
QuickUVM's `on_request` chain (monitor → analysis-fifo → responder-seq → sequencer → driver) is
*structurally identical* to tl_agent's — the gap is narrowly **the request queue**, not the
architecture. That a faithful clone would deadlock without it is **[P]**, not run.

---

## 4. How to close it (scoped, not built)

The root cause is one design fact: **`agents:` drives generation and env-wiring together.** The
feature is *decoupling wiring from generation for referenced agents*. Medium, ~5–7 days, staged:

- **Stage 1 (2–3 d) — generate-once / consume-by-reference.** `ProjectMeta.version`; a `vip:`
  top-level generation kind (VIP-only, no DUT, reusing `AgentConfig` verbatim); `AgentRef {name,
  manifest}` on the consuming bench; a `vip_manifest.qvip.j2` (name/version/package/types/filelist);
  three generator edits (skip source emission for an `AgentRef`; feed `AgentRef`s into the existing
  env wiring loop; emit `-F` chaining). Flips gap rows a–b, d.
- **Stage 2 (1–2 d) — VIP self-test bench.** `selftest: true` → two cross-connected interfaces, a
  host and a device agent, no DUT (the shape of `tl_agent/dv/tb/tb.sv`). Flips row c. **PASS bar met
  for a minimal VIP.**
- **Deferred:** adapter-inside-VIP (row e, a separate ownership axis); semver *resolution/conflict*;
  and the pipelined responder → it belongs to **T5**'s memory-model responder (a `respond:
  pipelined` shape + a request queue + source-id correlation), built once and inherited.

**Mutations decided for the build (from Stage 0):** M1/M2 above, re-run on the *generated* output;
plus a self-test-actually-tests proof (corrupt the device loopback, the self-test must go red — the
dead-responder trap has bitten this project repeatedly).

---

## 5. Measurement — structure, not LOC

Per the campaign's explicit caution (a LOC/class-count comparison *flatters* QuickUVM, since
protocol is hand-written under any methodology). The verdict rides on the *ownership* rows:

| structural axis | `tl_agent` | QuickUVM today | after the slice | discriminates? |
|---|---|---|---|---|
| manifest artefacts with identity | `.core` (VLNV) | **0** | 1 `.qvip` | **YES** |
| version field on the VIP | FuseSoC pin | **none** | `project.version` | **YES** |
| by-reference edges | ~30 consumers | **0** | 2 → 1 copy | **YES** |
| VIP self-test bench | `dv/tb/tb.sv` | **0** | 1 | **YES** |
| responder outstanding depth | 16 (queue) | 1 | 1 (deferred) | separate gap |

The verdict flips on the first four rows. Class/file counts are context, not evidence — reporting
them as the finding is exactly what the caution warns against.

---

## 6. Honest limits

- **Not built.** This assessment scopes the feature and proves its target is reachable; it does not
  implement it. The PASS bar is **not met** today.
- **Stage 0's consumers are hand-written**, standing in for generated ones. They prove the *seam*,
  not the *generation*.
- **Gap row e (adapter location) is [I]**, inspection only; the responder deadlock is **[P]**.
- **The pipelined responder is deferred to T5** — it is the same gap, and building it there once
  serves both.
- No `tl_agent` RTL/DV was vendored (unlike T1/T2): this target is agent-to-agent, and the question
  is about QuickUVM's *ownership model*, which is answered without reproducing the protocol.
