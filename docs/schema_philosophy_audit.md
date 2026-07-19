# Schema audit — "simple by default, powerful when needed", seven weeks in

An adversarial audit of QuickUVM's configuration schema against its own stated philosophy,
asking three questions: **(1)** has "simple by default, powerful when needed" actually been
respected; **(2)** are there redundant or contradictory configuration options; **(3)** how
*general* are the features versus overfit to the examples that motivated them.

**Method.** Four independent audit dimensions (simplicity, redundancy/contradiction,
generality, and an *empirical* prober that ran 16 adversarial configs through
`ProjectConfig.model_validate` + `Generator.generate_all`), every major/moderate finding then
adversarially re-verified against the code by a separate agent. Result: **18 findings
confirmed, 0 refuted, 0 overstated** — plus 13 explicit strengths. Quantitative backbone:
schema surface introspected from the Pydantic models, feature-usage matrix over all 50
example yamls, validator-growth timeline from git history.

---

## Verdict in three answers

**(1) The philosophy has been genuinely respected — at the layer it was aimed at.**
A 13-line YAML still generates a complete 23-file UVM bench; the entry barrier has *not
grown* while ~20 tier-4 features landed, because every advanced field defaults to the inert
simple case and opt-in containment is real (verified: adding a second agent leaves the first
agent's per-agent files byte-identical; `flat → packaged` is one knob, zero restructuring).
The fail-closed discipline even extends *into generated code* (the `UNFILLED_PREDICTOR`
fatal). The 245 rationale-bearing validators are of unusually high quality — the errors teach
the model, not just name the field.

**(2) The value space is guarded to an exceptional standard; the key space is fail-open.**
Nearly every semantically contradictory *value* combination hunted for is walled. But
31 of 33 model classes silently ignore unknown YAML keys, seven runtime-only fields are
accepted as user input, and a handful of value-level holes survive exactly one step outside
walls the project already built elsewhere. The suspected knob *overlaps* mostly dissolved
under inspection (emit_when vs request_valid: orthogonal; stimulus knobs: clean precedence)
— with one real exception (`count` vs `instances`).

**(3) The features are, with few exceptions, genuine primitives — but generality is
corridor-shaped at the structure tier.** The responder stack is a closed timing taxonomy
that survived the hardest available test (a full AXI slave fell out as pure composition;
the 5-slice epic needed one knob). The 1-example usage counts are mostly a weak signal —
probes, register coverage, emit_when, fields all pass the design test, and adversarial
composition (count×hybrid×request_ready, multi-clock×window) *worked*. The honest boundary
is the sparse composition matrix: ~55 of the 245 walls are "not yet" TODOs concentrated on
the structure features (count 9, instances 7, parameters 7, subenvs ~10), so "powerful when
needed" currently holds along example-walked diagonals, not as a free cross-product.

---

## The quantitative arc

| date (2026) | validators | models.py lines |
|---|---|---|
| 06-01 | 9 | 188 |
| 06-17 | 71 | 1,103 |
| 07-02 | 126 | 1,858 |
| 07-10 | 154 | 2,583 |
| 07-19 | 245 | 4,320 |

194 fields across 33 classes (AgentConfig 29, ProjectConfig 26). Validators grew **27×**
while fields grew ~5× — read both ways: the fail-closed discipline is enforced per feature
(good), *and* features do not freely compose (a fully orthogonal schema would not need
pairwise walls). Example yamls span 9 lines (subenv leaf) → ~25 (typical) → 102 (rvtimer
with RAL+CSR+coverage+assertions): a healthy gradient whose entry point never moved.

## The central structural finding

> **The fail-closed discipline lives at exactly one layer — value-level validation — and
> both neighboring layers leak.**

- **The key layer is fail-open.** Only `ProbeConfig` and `RegressConfig` (the two newest
  classes) set `extra="forbid"`. Everywhere else, unknown keys silently no-op. Proven live
  three ways: the committed `sat_adder.yaml` still carries stale pre-rename
  `trans_style: manual` (validated for weeks, does nothing); a typo'd agent key
  (`trans_stylo`) and an entire misspelled top-level block (`analyses:` for `analysis:`)
  both generate a runnable, green-looking bench with the intended config silently gone.
  Blast-radius test: forcing `forbid` everywhere breaks exactly **one** committed example —
  the stale specimen itself. The fix is nearly free.
- **The render-dispatch layer can silently drop validated knobs.** A knob can pass every
  validator and then never be consulted by the template branch that fires. Three confirmed:
  `tests[].sequence` is validated then ignored on any `count>1`/`instances` bench (the
  test runs the *default* sequence instead — and passes); `kind: vip` silently drops
  `probes`, `tests`, and `analysis` while its fence error names only three other sections;
  `register_model.bus_agent` accepts a responder agent, binding the RAL to a sequencer the
  forever-responder owns — the exact sequencer-clobber trap the project walls, with
  paragraph-length prose, on the other two doors (`tests[].sequence`, vseq steps).
- Corollary: **wall coverage is event-driven.** Each existing guard was added when a
  campaign hit the trap; the traps no campaign has walked yet (RAL-on-responder, stale
  keys, zero-period clocks) were still open. Guards need to be *derived* (e.g. "reject any
  section `files_to_generate` won't consume for this `kind`"), not accreted.

## Confirmed findings (18/18 survived adversarial verification)

**Major (7)**
1. Unknown keys silently ignored in 31/33 classes (fail-open front door). *Fix: default
   `extra="forbid"`, deprecation aliases for renamed keys; fixes cost one example edit.*
2. **README quickstart config fails validation** — the documented front door uses
   pre-rename `transaction:`/`trans_style:`; its file-set listing is also stale. *Fix: the
   README + a CI job validating every YAML block in docs against `ProjectConfig`.*
3. Runtime-only fields (`clocks`, `is_reference`, `ref_filelist`, `subenv_configs`, …)
   accepted as user YAML — `clocks:` acts as an accidental broken alias of the `clock:`
   list; `is_reference: true` fabricates a phantom VIP reference.
4. `register_model.bus_agent` accepts a responder → RAL frontdoor bound to an owned
   sequencer (silent-misgen; generated and confirmed).
5. `tests[].sequence` validated then silently dropped under `count>1`/`instances`.
6. Typo'd/unknown blocks generate green benches (the key-layer finding, proven end-to-end).
7. `kind: vip` fence incomplete (probes/tests/analysis silently vanish).

**Moderate (11, selected)**
- Default checking doesn't scale with default stimulus: agent #2 is auto-*driven* (default
  `auto_virtual_sequences`) but silently un-*scoreboarded* — the driven-but-unchecked
  silent-pass shape, one agent over from the predictor-stub fatal that guards agent #1.
- `respond:` is the *one* responder-only knob accepted inertly on an initiator (its six
  siblings are all rejected). One-line fix.
- `idle` + `respond: prefetch` validates but generates a bench that always fails
  `SILENT_RESPONDER` (prefetch has no per-cycle drive path).
- Numeric sanity holes: `clock.period: 0` → `forever #0` hangs at t=0 (in a project whose
  own comments say "a hung bench cannot report an error"); `num_items: 0` runs nothing and
  passes; unbounded `drive_offset_pct`.
- Three overlapping reset vocabularies: under `resets:`, `dut.reset`/`external_reset`
  become inert decoration with silent precedence.
- `count` vs `instances`: the same replication axis twice — `count` is *literally
  implemented* as degenerate `InstanceView`s yet is a separate, mutually-exclusive field
  carrying 9 walls (the most example-shaped corridor in the schema).
- `max_latency` confined to `out_of_order` is an implementation leak by its own comment
  ("the pool it stamps lives there"), not a scope statement.
- The ~55 "not yet" walls concentrate on structure features — publish the composition
  matrix (it already exists as error strings) to convert limitation into scope.

**Strengths worth naming (13 confirmed, selected)**
- 13-line minimal yaml → 23-file bench; entry barrier flat across 7 weeks of features.
- Opt-in containment empirically real; growth requires no restructuring (initiator →
  responder keeps the port-direction model; flat → packaged is one knob).
- The responder `respond:` enum is a *timing taxonomy* (response-slack × outstandingness),
  not accreted protocol flags — proven by AXI falling out as composition.
- Walls are rationale-bearing design theorems where they are principled (window×two-stream,
  proactive×on_request, the observed-clock rules).
- `ProbeConfig` reuses `PortConfig`'s type machinery by reference — the internal signature
  of a genuinely general primitive.
- The trajectory is **converging**: later campaigns increasingly closed by composition or
  zero-code findings (axi_slave, ahb_regs, cdc_fifo, T4), six "it breaks" predictions
  refuted against one confirmed ceiling. The alert_handler line (proactive+count+window) is
  the apparent counter-example that proves the rule: each knob is protocol-agnostic and two
  of the three composed (alert_array) instead of needing a fourth flag.

## Prioritized recommendations

1. **Close the key layer** (major, ~free): `extra="forbid"` as the shared-base default;
   deprecation aliases that *error with the rename hint*; fix `sat_adder`'s stale key;
   reject runtime-only fields in user input via a `mode="before"` validator.
2. **Fix the front door** (major, trivial): README config + file listing; CI-validate every
   doc YAML block (hang it on the existing byte-identity machinery).
3. **Close the three silent-misgen holes** (major): bus_agent-on-responder (reuse the
   existing error prose), tests[].sequence×count/instances (honor or reject), the vip fence
   (derive from `files_to_generate`).
4. **One-line walls**: `respond:` on initiator; `idle`×`prefetch`; `period>=1`;
   `num_items>=1`; `drive_offset_pct` bounds; reset-vocabulary precedence.
5. **Warn on the unscoreboarded second agent** (the driven-but-unchecked default) with the
   `analysis: {scoreboards: []}` explicit opt-out the predictor fatal already models.
6. **Decide `count` vs `instances` before the corridor calcifies**: fold `count` into
   `instances` as shared-DUT sugar, or commit to it and schedule the wall-lifts.
   *RESOLVED — a third way: inspection showed they are not one axis but a topology ×
   variation matrix (identical copies × one vectored DUT vs parameterized variants ×
   per-instance DUTs; the parameterized-shared cell is impossible, so the mutual
   exclusion is a theorem, not a pending unification). Both stay; `count:` renamed
   `replicas:` so the names carry the separation — which also retires the schema's
   last `count` homonym. The old key errors with a rename hint.*
7. **Publish the composition matrix** (feature × feature: works / wall / untested) in
   `comparison.md` — the information already exists as error strings; surfacing it turns
   apparent limitation into stated scope.

## Threats to validity

Single-audit snapshot; probes covered 16 combos, not the full cross-product; "generality"
judged by design + composition behavior, which can still miss protocol families no example
has approached (analog-ish interfaces, credit-based flow control). The verify pass guards
against overclaiming within what was probed, not against unprobed unknowns.
