# QuickUVM parity roadmap (v0.9 → v1.0)

Goal: make QuickUVM a credible **general-purpose** UVM generator for any digital
functional-verification project — not just single-block, single-protocol benches —
while preserving its identity (simplicity + fail-closed pragma preservation).

See `comparison.md` for the current capability matrix, `code_preservation.md` for the
merge contract every phase must keep intact, and [`defaults.md`](defaults.md) for the
**sane-defaults spec** (what a generated bench looks like out of the box, and the
open-source evidence behind each choice).
[`comparison_opentitan.md`](comparison_opentitan.md) is a structural gap analysis vs a
mature industrial bench (OpenTitan `rv_timer`) — it surfaced **C5** below and raised the
priority of **V2**/**R1**.

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
effort sink in a real bench (cf. the SPI bridge's `<dut>_reference_model` `predict()`), so a generated
**predictor seam** (bring-your-own golden model over DPI-C) is high-leverage too.

So this revision leads with **stimulus richness + coverage + a reference-model seam**,
then **reuse**, then **checking generality** and **infra/clocking**. RAL block
*generation* is intentionally left to external tools (reggen/SystemRDL); QuickUVM owns
the *wiring*, which is done.

## What's already shipped (v0.4 → v0.9)

| Phase | Result | Version |
|---|---|---|
| Pragma preservation hardening (Track A) | fail-closed merge + rolling backups; latent `{%-` defect fixed | — |
| F1 — Config objects + `uvm_config_db` | `<agent>_cfg`/`<dut>_env_cfg`; `is_active` wired | v0.3.0 |
| C1 — Analysis fabric (MVP per-agent routing) | opt-in `analysis:` (coverage list + scoreboards) | v0.4.0 |
| C4a — RAL front-door wiring | adapter skeleton + build/lock/predictor + `reg_test` | v0.5.0 |
| C4b — RAL backdoor | `backdoor_root` → `add_hdl_path`; backdoor `reg_test` | v0.6.0 |
| UVM version selector | `project.uvm_version: 1.1d \| 1.2` | v0.7.0 |
| C4c — Custom `uvm_reg_frontdoor` | generated skeleton + `set_frontdoor` | v0.8.0 |
| Scoreboard `sb_enable` / `sb_flush` | disable on reg tests; configurable startup flush | v0.9.x |

These stay as-is. The register pillar (wiring) is considered **done**; block generation
is delegated to reggen.

## Identity constraints (every phase)

Guiding principle: **simple by default, powerful when needed** (the KDE Community maxim).
QuickUVM must stay quick to adopt and useful in education/small-block bring-up even as it
grows toward industrial-grade capability. Each phase is judged against a **simplicity
budget** — if it raises the entry barrier for the simple case, redesign it as
opt-in/layered.

- **Simple path stays simple.** The minimal config → running bench, and the flat
  single-package default, must not get harder because an advanced feature exists.
- **Opt-in & byte-identical when unused.** New config blocks leave existing output
  unchanged when omitted (as C1/C4 already do) — progressive disclosure, not a tax on the
  basic case.
- **Sane defaults, escape hatches.** Good defaults out of the box; arbitrary complexity
  goes through the pragma/user-code regions, not ever-growing config.
- **Fail-closed preservation preserved.** Extend the marker-regression suite to each new
  config shape (rich transactions, params, vseqs, subenvs).
- **Skeleton, not magic.** Generated logic that can't be inferred stays in pragma regions
  — but the *default skeleton must encode good patterns* (see X0).

## X0 — External-reset support — DONE

Origin: the default driver/monitor drove/sampled without waiting for reset, which bit a
downstream SPI bench. **A design review (4 proposals, adversarially judged) reframed this:**
an *auto* reset-gate has no safe generic target — for an agent-driven reset (a randomized
input port) a `wait` would deadlock the driver against itself, and for an external reset
the generated interface never declared the signal, so `vif.<reset>` was undeclared and the
wait wouldn't compile. So the real fix is an explicit, opt-in **external-reset feature**,
not a silent default.

Shipped: `dut.external_reset: bool = false`. When true (and `dut.reset` is set and is *not*
an agent input port — validated), QuickUVM:
- declares the reset as an **interface port** (`interface foo (input clk, input rst_n);`),
- generates a **`reset_generator`** in top (a pragma region — assert then deassert) and
  passes the reset to each interface (named ports),
- **reset-gates** the driver (`initialize` waits for deassert + settle) and the monitor
  (`run_phase` waits before the first sample).

Byte-identical when false (verified: spi regen is a no-op; simple_reg leaks nothing).
Verible-lint clean for the external path. Covered by `tests/test_external_reset.py`.
Note: the monitor's protocol-specific framing/sampling robustness (the SPI "blind loop")
stays user pragma code — the generic skeleton can't know the protocol.

## Combinational DUT support — DONE

From the example-library effort (`examples/barrel_shifter/`): pure combinational blocks
(no clock/state) are a flexibility stress test for a clock-centric generator. Opt-in
`dut.combinational: bool = false`. When true: the generated clock is kept as a TB
**cadence** (one vector/cycle) but NOT connected to the DUT; the DUT stub is
`always_comb`; and the monitor samples inputs AND outputs **together** (0-cycle latency)
race-free through a dedicated **monitor clocking block** (`mon_cb`, all signals
`input #1step`) — vs the default monitor's input→`@cb1`→output pattern that suits a
registered (1-cycle-latency) DUT. The cadence period must exceed the DUT's combinational
settling time (it also gives glitch-free, delay-tolerant sampling). Mutually exclusive
with `external_reset`. Byte-identical when false. Validated end-to-end: a parameterized
barrel shifter passes 501/501 on Xcelium with zero clock/monitor manual edits (only the
golden model + op constraint are user code). Covered by `tests/test_combinational.py`.

**Follow-up to evaluate:** the `mon_cb` race-free sampling is currently scoped to
combinational. Making it the default for *registered* monitors too (sampling driven
inputs through a clocking block instead of raw) would harden every generated monitor —
but it changes the input↔output alignment handling and is not byte-identical, so it needs
its own decision + validation.

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

**Status — first slice landed (enum/typed fields + per-field constraints):**
- `PortConfig.enum` → QuickUVM generates the testbench's OWN `<name>_e` typedef and
  a `rand <name>_e` field that self-constrains to its legal values. **Black box by
  default**: the TB encodes the spec independently of the DUT — a wrong DUT encoding
  is *caught*, not mirrored (proven in `examples/alu/` by a mutation test: swapping
  the DUT's SRL/SLT opcodes yields 216 scoreboard failures).
- `PortConfig.type` + `project.imports` → the white-box escape hatch: reference an
  EXTERNAL spec/DUT type (powerful when genuinely shared).
- `PortConfig.constraint` → a per-field expression collected into a `qcfg_c`
  transaction constraint block.
- Byte-identical when unused (a plain `name+width+rand` field emits the legacy SV).

**Status — second slice landed (variable-length payload + transaction constraints):**
- `agents[].fields:` → **transaction-only** data that is NOT an interface wire: a
  `rand` **dynamic array** (`bit [W-1:0] x[]`) or **queue** (`x[$]`), with
  `uvm_field_array_int`/`uvm_field_queue_int` automation and an auto size-bound
  (`min_size`/`max_size`) so an unconstrained array can't randomize to a runaway
  size. The bus (de)serialization stays user pragma code ("skeleton, not magic").
- `agents[].constraints:` → a **transaction-level** list of raw SystemVerilog,
  emitted into a `trans_c` block. One mechanism covers **inter-field relations**
  (`len == payload.size()`), **`dist`** weighting, **`soft`** defaults, and payload
  sizing — powerful, no new schema, fail-closed on names/uniqueness/empties.
- Fail-closed validation: field names are legal SV identifiers, unique across
  ports+fields; size bounds are sane; constraint expressions are non-empty.
- Byte-identical when absent (no `fields`/`constraints` → no `trans_c`, no members).
- Validated on `examples/packet/` (a combinational checksum DUT): a `rand byte
  payload[]` packed onto a wide bus, with `len == payload.size()` and a length
  `dist` — **TEST PASSED 61/61 on Xcelium**, lengths span `[1:16]` with the dist's
  short-packet bias; verible-lint-clean; CI gates it.

**Status — third slice landed (packed composite port fields):**
- A port may declare a fixed-width composite: a multi-dim **packed array**
  (`packed_dims: [4, 8]` → `bit [3:0][7:0]`) or a **packed struct**
  (`struct: [{name, width}, ...]` → a generated `<name>_t` typedef). These ride the
  interface as **raw bits** (`logic [bit_width-1:0]`, like enum), while the
  transaction declares the composite SV type — the driver packs and the monitor
  unpacks via plain integral assignment (no `$cast`). A new `bit_width` property
  drives the interface/DUT widths, the coverage range-check, and the K0 DPI ≤64-bit
  limit (a ≤64-bit packed field marshals as one DPI scalar; wider is rejected).
- Fail-closed: `enum`/`type`/`packed_dims`/`struct` are mutually exclusive; dims ≥1
  and non-empty; struct members are legal, unique identifiers; `incrementing` is
  rejected on a composite field.
- Byte-identical when unused (a scalar port has `bit_width == width`).
- A struct **member** may itself be a packed array (`packed_dims`) or a NESTED
  packed struct (`struct`, recursive) — each nested struct is emitted as its own
  **named** `<port>_<path>_t` typedef (innermost first; verible disallows anonymous
  structs) and referenced by name, so the reference model can use deep typed access
  (`hdr.tag.cls`). `bit_width` recurses through the tree.
- Validated on `examples/vec_unit/` (a combinational unit with a packed-struct
  header whose `tag` is a nested `{cls, id}` struct + a packed array of lanes; the
  reference model uses typed access `hdr.en`/`hdr.tag.cls`/`lanes[i]`) — **TEST
  PASSED 51/51 on Xcelium**; verible-clean; CI-gated.
- A struct member may also be an **`enum`** (a generated `<port>_<path>_e` typedef
  using the member `width` as the encoding width, emitted before the struct that
  references it) — so a member self-constrains to its legal codes. `examples/vec_unit/`
  now makes `hdr.tag.cls` an enum (still 51/51 on Xcelium); composite/enum members are
  all named typedefs (verible-clean).
- **Per-field `rand_mode`** (`rand_mode: false`) declares a field `rand` but disables
  its randomization by default (`<field>.rand_mode(0)` in the transaction's `new()`),
  so it holds its value until a sequence re-enables it (`tr.<field>.rand_mode(1)`).
  Fail-closed: only valid on a rand input port. Validated on `examples/gated_add/`:
  `bias` is held at 0 in `rand_test` (`y == a`) and randomized in `bias_on_test`
  (`y == a + bias`) — both **41/41 on Xcelium**; byte-identical when unused.
- *Remaining:* structured (schema) sugar for `dist`/`soft` (raw-SV `constraints:`
  already expresses both).

### V1 — Functional coverage from fields  *(highest leverage; coverage)*
Derive a real covergroup from the transaction/config fields the generator already has:
config-driven coverpoints + bins, optional crosses, sampled from the monitor's analysis
write. Opt-in `coverage_models:` block; default stays the generic stub.
**Accept:** coverpoints/bins for a transaction's fields generate and accumulate.

**Status — first slice landed (config-driven covergroup):**
- `coverage_models:` (a list, one entry per agent) → QuickUVM generates a real
  covergroup in `<agent>_cov`: config-driven coverpoints with named **bins**
  (`value` / `range` / `values`), **enum fields auto-bin** one-per-label, **crosses**
  (`[a, b]` → `a_x_b : cross a_cp, b_cp`), and per-coverpoint `at_least`. Sampled on
  the existing monitor analysis write — no new plumbing.
- Fail-closed validation: field must be a port of the agent; bin values must fit the
  field width; a wide (>1-bit) plain field requires explicit bins (no vague
  auto-partition); a cross must reference declared coverpoints.
- Byte-identical when absent (the generic `bins x[8] = {[0:$]}` stub stays).
- **Black box**: bins encode the spec's interesting values (corners/ranges), not DUT
  internals. Validated on `examples/alu/` — 28/64 bins, 55.56% after 1001 random
  vectors on Xcelium; verible-clean; CI gates it (the alu lint step).

**Status — second slice landed (closure machinery):**
- Per-coverpoint **`illegal_bins:`** (flag a hit as an error) and **`ignore_bins:`**
  (drop don't-cares from the denominator) — both reuse the `value`/`range`/`values`
  bin schema and coexist with enum/wide auto-bins (only an explicit `bins` suppresses
  auto-binning). Per-coverpoint **`transitions:`** (`{name, seq}`) emit temporal
  `bins <name> = (a => b);`. Covergroup-level **`goal:`** → `option.goal`.
- Fail-closed validation: bin names unique across all four lists; bin + integer
  transition-endpoint values are storable — a **declared enum label** for an enum
  field (an out-of-label value is silently *dropped* by the simulator, OBINRGE, so
  it's rejected at config time) or within the width range for a plain field; a
  transition `seq` needs ≥2 non-empty `=>`-separated states; `goal` is a 1..100
  percent. A wide plain field is satisfied by bins **or** transitions.
- Byte-identical when absent (no `goal`, no new lists → the first-slice output).
- Validated on `examples/alu/` (`op` ignores a WIP opcode; `carry` gains rise/fall
  transition bins; `goal: 90`) — **TEST PASSED 1001/1001 on Xcelium** — and on
  `examples/packet/`, which carries an **enforceable** `illegal_bins` on the 16-bit
  `sum`: a checksum of ≤16 bytes can never exceed `16*0xFF`, so values above that are
  impossible-by-construction and the bin is *live* (storable) yet never hit by a
  correct DUT — **61/61 with no illegal firing**. Both verible-clean; CI-gated.
- **`binsof` cross selection**: a cross may be the plain `[a, b]` form (unchanged) or
  a `CrossSpec` `{fields, bins, name}` whose `bins`/`ignore_bins`/`illegal_bins` carry
  raw `binsof(...)`/`intersect`/`&&`/`!` select expressions, and an optional `name`
  (so two crosses can span the same fields). Fail-closed: duplicate cross names and
  cross-bin names are rejected, names are SV identifiers, a select is non-empty.
  Byte-identical for a plain cross. Validated on `examples/alu/` (`add_corners`
  refines `op × a` to ADD at the operand corners, ignoring mid) — **1001/1001 on
  Xcelium**; verible-clean.
- **`auto_bin_max`**: a coverpoint may cap its automatic-bin count
  (`option.auto_bin_max = N`) — and setting it lets a **wide plain field** be
  auto-binned into N buckets instead of requiring explicit bins (the "needs bins"
  rule is relaxed). Fail-closed: rejected alongside explicit `bins`/`transitions`
  (which suppress auto-binning), and must be ≥1. Validated on `examples/alu/`
  (`result` auto-binned into 16) — **1001/1001 on Xcelium**; byte-identical when unset.
- *Remaining:* a deliberate illegal-hit negative test, and the coverage-merge/report
  flow (roadmap **R1**).

### S2 — Sequence library
Generate more than one base sequence: a small library (incrementing/random/directed),
reset and error-injection sequence skeletons, and a sequence-of-sequences. Config-driven
test → sequence selection (replace the bare `num_items`).
**Accept:** a test selects from ≥2 generated sequences + a reset sequence.

**Status — first slice landed (per-agent library + test selection):**
- `agents[].sequences:` → a library of sequence classes per agent. `kind: random`
  (the do_item/randomize loop) and `incrementing` (steps a plain field via
  `tr.<field> == <W>'(i)`) generate working bodies; `directed`/`reset`/`error`
  generate a skeleton with a `// pragma quickuvm custom body` region.
- `tests[].sequence: {agent, name}` → the test starts the selected library
  sequence on that agent's sequencer instead of the default `<primary>_seq`.
- Fail-closed validation: sequence names must be legal, non-reserved SV identifiers
  and unique (and must not collide with `<agent>_seq`); `incrementing` needs a
  plain (non-enum/typed, unconstrained) randomizable field; a selector must name a
  declared sequence on an **active** agent.
- Byte-identical when unused. Validated on `examples/barrel_shifter/` — `rand_test`
  501/501 and `amt_sweep` (the incrementing `bs_amt_walk`) 33/33 on Xcelium;
  verible-lint-clean; CI gates it.

**Status — second slice landed (composition + per-test parameters):**
- `kind: nested` + `steps: [...]` → a **sequence-of-sequences**: the named sibling
  library sequences are created and `start(m_sequencer)`-ed in order on this
  sequence's own sequencer (single-agent analogue of a C2 virtual sequence; a
  repeated step gets a distinct `step_<i>` handle). Fail-closed: every step is a
  declared, **non-nested** sequence of the same agent and not itself (no cycles).
- **Per-test count override**: a library sequence's length is now a settable
  `int count` member, and `tests[].sequence: {agent, name, count: N}` sets it before
  `start` — the same sequence runs at different lengths per test (rejected on a
  nested selector, which has no item count).
- Byte-identical when neither is used (a library seq just gains the `count` member,
  which is a deliberate, regenerated change for the two library-using examples).
- Validated on `examples/barrel_shifter/`: `bs_smoke` (nested: walk-then-soak) runs
  **289/289**, `short_sweep` (`bs_amt_walk` with `count: 8`) runs **9/9** vs the full
  `amt_sweep` **33/33** — proving both composition and override on Xcelium;
  verible-clean; CI-gated.
- *Remaining:* concrete reset/error bodies (vs skeletons — genuinely
  protocol-specific) and per-test constraint/knob overrides beyond `count`.

### C2 — Virtual sequencer + virtual sequences
`<dut>_virtual_sequencer` (agent sequencer handles) + `<dut>_base_vseq`; tests run vseqs. Required for any
multi-interface DUT (i.e. most DUTs).
**Accept:** a vseq coordinating ≥2 agents.

**Status — landed:**
- `virtual_sequences:` → QuickUVM generates `<dut>_virtual_sequencer` (a handle to each active agent's
  sequencer, wired in the env's `connect_phase`), `<dut>_base_vseq`
  (`` `uvm_declare_p_sequencer(<dut>_virtual_sequencer) ``), and one class per vsequence whose body
  starts per-agent sub-sequences `sequential` (in order) or `parallel` (`fork…join`).
- `tests[].sequence` vs `tests[].vseq` select single-agent vs virtual-sequence
  stimulus (mutually exclusive); a vseq runs on `e.vsqr`.
- **Sane default (see [`defaults.md`](defaults.md)):** with **≥2 active agents and no
  explicit `virtual_sequences`**, QuickUVM auto-scaffolds the vsqr + a default
  `<dut>_vseq` (parallel) firing each agent's base sequence, and the default test
  runs it. `auto_virtual_sequences: false` / `auto_vseq_mode:` are the knobs; single-agent
  and explicit-vseq benches are byte-identical.
- The default `tb_top.sv` DUT connection now wires **all** agents' ports (was
  primary-only), so a multi-interface DUT connects out of the box.
- Fail-closed validation: vseq names are legal/unique/non-reserved; steps target an
  active agent and an existing library (or default) sequence; a test's vseq must exist.
- Byte-identical when absent. Validated on `examples/fifo/` (a 2-agent synchronous
  FIFO): the sequential `smoke_vseq` passes a **strict data-integrity check**
  (16/16, 0 errors) and the parallel `stress_vseq` runs a concurrent soak — both on
  Xcelium; verible-lint-clean; CI gates it.
- *Note:* strict checking of the concurrent stream uses a hand-wired two-stream
  model (one analysis fifo per agent) — the generalized cycle-aligned multi-stream
  scoreboard is roadmap **A2**.

### K0 — Reference-model / DPI-C predictor seam  *(checker; inspired by HDL Verifier)*
The scoreboard predictor is the biggest hand-written-effort sink in a real bench, and
UVMF/Easier UVM leave it entirely to the user. Rather than synthesize a predictor,
generate the **seam** so a golden model drops in:
- a defined predictor interface — a `uvm_component` with one `predict(req) → exp` method —
  so the scoreboard is checker-agnostic (replaces today's ad-hoc `<dut>_reference_model` blob);
- optional **DPI-C scaffolding** (`import "DPI-C"` decls + a C/C++ header & stub whose
  signature is derived from the transaction fields) so the golden model can be written in
  C/C++ instead of SystemVerilog, then called per transaction;
- the scoreboard wiring that routes the monitored transaction through the predictor.

The reference-model *body* stays user code (SV or C); QuickUVM owns the interface + bridge.
This is the lever HDL Verifier exploits, minus the MATLAB/Simulink front-end (out of scope).
**Accept:** a transaction round-trips through a DPI-C golden-model stub into the scoreboard.

**Status — landed:**
- The predictor seam already existed: `<dut>_predictor.predict(req) → exp`, body in
  `<dut>_reference_model.svh`. K0 adds the **DPI-C option** via a
  `reference_model: {language: sv | c}` block (default `sv`, byte-identical).
- `language: c` → a **fully-generated SV marshaling bridge**
  (`import "DPI-C" function void <dut>_predict(...)` + a `predict()` that copies the
  transaction, calls the C function, unpacks the expected outputs) plus a
  **`<dut>_reference_model.c` stub** (the only file the user edits) whose signature is
  derived from the primary agent's fields; the `.c` is added to the generated `run.f`.
- Scalar marshaling by width: ≤8→`byte`/`char`, ≤16→`shortint`/`short`, ≤32→`int`/`int`,
  ≤64→`longint`/`long long` (inputs by value, outputs by pointer); enum/typed fields are
  cast. Fail-closed: a >64-bit field on the `c` path is rejected (packed `svBitVecVal`
  marshaling is a follow-up). The `.c` pragma region is preserved on regeneration.
- Validated on `examples/sat_adder/` (a combinational saturating adder, golden model in
  C): the transaction **round-trips through the DPI-C model into the scoreboard, 201/201
  on Xcelium**; SV is verible-lint-clean; CI gates it.
- *Remaining:* C++/SystemC bodies, >64-bit (packed) marshaling, per-scoreboard language
  once A2 (multi-stream) lands.

With K0, the **General-DV MVP is complete** (X0 + S1 + V1 + S2 + C2 + K0): stimulus,
field-derived coverage, multi-agent coordination, and a bring-your-own golden model
(SV or C) checking seam.

## Priority tier 2 — reuse / architecture

### F2 — VIP package restructuring — DONE
`layout: flat | packaged`. `packaged`: standalone `<agent>_pkg`, `<env>_pkg`, thin bench,
per-package `.f`. Unlocks separate compilation, versioning, and cross-project reuse.
**Accept:** `<agent>_pkg` compiles standalone; `layout: flat` stays byte-identical. ✅

**Status — landed:**
- `layout: packaged` splits the flat `<dut>_tb_pkg` along its dependency seams into a
  standalone `<agent>_pkg` per agent (the reusable VIP — imports only `uvm_pkg` + the
  interface), a `<dut>_env_pkg` (scoreboard + env, imports the agent packages), and a
  `<dut>_test_pkg` (the tests, imports the env). Each gets its own `.f` filelist
  (`<agent>_pkg.f`, `<dut>_env_pkg.f`, `<dut>_test_pkg.f`) chained via `-f`, and the
  bench (`tb_top`) just imports the test package. `layout: flat` (default) keeps the
  single `<dut>_tb_pkg` + `pkg.f` — **byte-identical** (the per-component `.svh` files
  are unchanged; only their grouping into packages differs).
- Validated on `examples/vip/`: the agent VIP compiles **standalone**
  (`xrun -uvm -compile -f io_pkg.f` → 0 errors, the Accept criterion), and the full
  packaged bench runs **51/51 on Xcelium**. verible-lint-clean; CI gates it.

### C3 — Parameterization
`parameters:` at interface/agent/env/bench; param refs in field widths; `#(...)` threaded
via Jinja macros.
**Accept:** one agent reused at two widths.

### H1 — Sub-environments
`subenvs:`; nest child env packages + configs + param propagation. Depends F1/F2/C1/C3.
**Accept:** a subsystem env composes ≥2 block envs.

## Priority tier 3 — checking generality

### A2 — Scoreboard / comparison-strategy library — DONE
Builds on the K0 predictor seam: in-order (today) **plus** out-of-order, latency-windowed,
and multi-stream comparators; "A drives → predictor → scoreboard ← B monitors" topologies
and multi-transaction-type scoreboards (the full fabric C1 deferred). K0 supplies the
swappable predictor; A2 supplies the comparison strategies around it.
**Accept:** an out-of-order scoreboard matches a reordering DUT model. ✅
Complete: two-stream topology, in-order + out-of-order matching, the latency window, and
multi-transaction-type scoreboards all landed (see the status blocks below).

**Status — multi-transaction-type landed (A2 complete):**
- With **≥2 scoreboards** in the `analysis:` block, each gets its OWN typed
  predictor/comparator/scoreboard/reference-model set, prefixed `<dut>_<sbname>_*`,
  so a DUT with several differently-typed output channels is checked by one
  scoreboard per channel. With ≤1 scoreboard the single `<dut>_*` set is kept
  **byte-identical**. The "sole two-stream scoreboard" guard is lifted (two-stream
  still requires `reference_model.language: sv`).
- Validated on `examples/splitter/` (one request stream → two different-typed
  channels: an 8-bit *sum* and a 1-bit *flag*): the `sum_sb` and `flag_sb`
  scoreboards each match **30/30 on Xcelium**; breaking one channel's golden model
  fails only that scoreboard (27/30) while the other stays 30/30, proving they check
  independently. verible-lint-clean; CI gates it.

**Status — out-of-order matching landed (Accept bar met):**
- `match: out_of_order` + `match_key:` on a two-stream scoreboard swaps the in-order
  FIFO pair for a **queue-per-key pool**: the comparator pools expected responses by
  tag (request order within a key) and matches each actual to its key's queue front,
  so a reordered response stream is checked correctly. An actual with no pending
  expected → error; pooled expected never matched → `SB_LEFTOVER`. Queue-per-key (not
  a single slot) is robust to tag reuse — a reused tag stays in-order within its key.
  `in_order` (default) is byte-identical.
- Validated on `examples/reqrsp/` grown to **two latency lanes** (routed by
  `req_id[0]`, latencies 2 and 5): responses overtake and reorder. **Out-of-order
  matches 30/30 on Xcelium; the same DUT with `in_order` fails 18/30**, proving the
  reordering is real and that keyed matching is what fixes it. A no-collision
  invariant (odd latency difference + requests paced every two cycles → the lanes
  never complete the same cycle) keeps the DUT to a clean OR-mux, guarded by an
  assertion. verible-lint-clean; CI gates it.
- **Latency window landed:** `max_latency: <cycles>` on an out-of-order scoreboard
  stamps each pooled expected with `$realtime` and flags (`SB_LATENCY`) a response
  that arrived later than the window (cycles × clock period, emitted as a timescale-
  independent time literal); a never-arriving response is caught by `SB_LEFTOVER`, and
  the data check is not skipped on a late match. The window is end-to-end *monitored*
  latency (req-monitor → rsp-monitor sample points). Validated on `reqrsp`:
  `max_latency: 8` passes 30/30, `max_latency: 3` fails every slow-lane (5-cycle)
  response while the fast lane passes.
- *Remaining A2:* multi-transaction-type comparators (≥2 source/monitor type pairs
  in one scoreboard) — its own slice.

**Status — first slice landed (two-stream in-order topology):**
- `analysis.scoreboards[].monitor:` turns a scoreboard two-stream: the `source`
  agent (input/stimulus) feeds the predictor and the `monitor` agent (output) is
  the comparator's "actual" — generalizing the "A drives → predictor → ← B monitors"
  wiring the fifo example used to hand-wire. The predictor seam generalizes to
  `predict(source_item) → monitor_item`, the comparator/expected are typed on the
  monitor stream, and the scoreboard grows `src_axp`/`mon_axp`. Single-stream
  (no `monitor`) is byte-identical: `predict(pa)→pa`, one `axp`.
- `AgentConfig.emit_when:` — the monitor publishes a transaction only when a
  valid/handshake port is high, so idle / pipeline-fill cycles never enter the
  scoreboard and the i-th request lines up with the i-th response. Byte-identical
  when unset.
- Fail-closed validation: `monitor` names an existing agent and differs from
  `source`; a two-stream scoreboard must be the sole scoreboard (one source/monitor
  type pair) and requires `reference_model.language: sv` (DPI-C two-type marshaling
  TBD); `emit_when` names a sampled port.
- Validated on `examples/reqrsp/` (a tagged request/response unit, single in-order
  lane): `predict(req) → expected rsp` matched against the observed response stream,
  **30/30 on Xcelium**; a golden-model mutation is caught (27/30 fail), proving the
  check is real; verible-lint-clean; CI gates it.
- *Next slices:* out-of-order keyed matching (`match: out_of_order` + `match_key:`)
  for a reordering DUT — the A2 **Accept** bar; then latency-windowed and
  multi-transaction-type comparators. The reqrsp example grows a second lane (a
  different latency → reordering) to drive the out-of-order slice.

### K1 — Assertion / protocol-checker scaffolding
Generate an interface assertion module + SVA hook pragmas (protocol properties are user
code, but the binding/structure is scaffolded).
**Accept:** an `*_if` emits a bound checker module with a sample property.

### C5 — RAL-driven CSR test library — DONE  *(surfaced by the OpenTitan comparison)*
Generate the standard, register-model-driven CSR test suite that every real register block
needs and that QuickUVM is ~90% positioned for (it already wires the RAL): `csr_rw`,
`csr_bit_bash`, `csr_aliasing`, `csr_hw_reset`, and `mem_walk`. These are RAL-generic — the
bodies are UVM `uvm_reg`-based sequences (or thin wrappers over them), parameterized by the
external reg block QuickUVM already builds/locks/adapts. Today QuickUVM emits only a basic
`reg_test` (read/write). See [`comparison_opentitan.md`](comparison_opentitan.md): the full
CSR suite is the single biggest *generatable* gap vs an industrial bench (in OpenTitan every
cip block inherits it for free from `csr_utils`).
**Accept:** a register block generates a `csr_rw`/`bit_bash`/`hw_reset` test that runs
against the RAL and passes.

**Status — landed:**
- `register_model.csr_tests: [hw_reset, bit_bash, rw, mem_walk, shared]` → one
  `<dut>_csr_<kind>_test` per kind, each running the matching UVM built-in register
  sequence (`uvm_reg_hw_reset_seq` / `uvm_reg_bit_bash_seq` / `uvm_reg_access_seq` /
  `uvm_mem_walk_seq` / `uvm_reg_shared_access_seq`) on the locked RAL, with the
  data-path scoreboard disabled (the RAL is the checker). Run via `+UVM_TESTNAME`.
  Sits alongside (does not replace) the existing `reg_test`. Kinds are deduped and
  schema-validated; byte-identical when `csr_tests` is empty. Each kind uses its
  built-in sequence's natural door (independent of `reg_test_door`); `rw` needs a
  `backdoor_root`, and `mem_walk`/`shared` no-op without a `uvm_mem` / a 2nd map.
- **Runnable RAL example (`examples/regfile/`)** — fills the long-standing "no
  runnable RAL example" gap: a 4×16-bit register DUT, a hand-written external
  `uvm_reg_block` (reggen-style, with backdoor HDL slices), the generated host
  agent / adapter / predictor, and `csr_tests: [hw_reset, bit_bash, rw]`. On
  Xcelium all four tests are GREEN (0 warn/err): the `rand_test` data-path
  scoreboard (42/42 vs a golden model) **and** the three CSR tests; `rw`
  (`uvm_reg_access_seq`) exercises the frontdoor↔backdoor path via `backdoor_root`.
- Shook out two generator fixes: the env adapter **handle** is now `bus_adapter`
  (was `reg_adapter`, which shadowed a user adapter class literally named
  `reg_adapter` — `handle::type_id::create` failed to bind); and a
  deliberately-disabled scoreboard now reports an info line instead of a spurious
  `NOVEC` warning.

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
  *(The OpenTitan comparison raises this: cip blocks sample reggen-emitted reg covergroups
  as a matter of course — promote V2 alongside C5 for register-heavy DUTs.)*
- **A1 — QVIP / external-VIP integration** — niche.
- **Mixed-language (VHDL) / BFM / emulation** — large effort, narrow audience; UVMF's
  domain.
- **RAL block generation** — delegated to reggen/SystemRDL by design.

## Suggested sequencing

```
X0 external-reset support (DONE)
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

Recommendation: with **X0 done**, pursue the rest of the
**General-DV MVP** (stimulus + coverage + virtual sequences + reference-model seam) —
these are the pillars that bite *every* project. Defer reuse/hierarchy/infra until a
multi-block or closure-driven need forces them. QuickUVM's niche remains simplicity +
best-in-class code preservation.
