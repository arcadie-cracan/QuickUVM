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

### C3 — Parameterization — DONE
`parameters:` at interface/agent/env/bench; param refs in field widths; `#(...)` threaded
via Jinja macros.
**Accept:** one agent reused at two widths. ✅

**Status — multi-instantiation landed (Accept met):**
- `instances:` on a parameterized agent instantiates the SAME VIP more than once at
  different values in **one** bench (e.g. `{name: io8, values: {W: 8}}` +
  `{name: io16, values: {W: 16}}`). The VIP class set is generated **once**
  (parameterized); the env/top then wire, per instance, its own interface
  (`io_if#(8)`/`io_if#(16)`), DUT (`twowidth#(8)`/`twowidth#(16)`), agent
  (`io_agent#(8)`/`io_agent#(16)`, distinct `io8_vif`/`io16_vif` keys), and a concrete
  scoreboard set (`<dut>_io8_*` on `io_seq_item#(8)`, `<dut>_io16_*` on `#(16)`); the
  test forks one sequence per instance. **Opt-in: an agent with no `instances` is
  byte-identical.**
- The scoreboard trio is generated **concrete per instance** (not a parameterized
  class): SystemVerilog forbids an out-of-block method definition using
  class-specialization syntax (`function … io_predictor#(W)::predict`), so a
  parameterized predictor can't keep its `predict()` in a separate reference model —
  Xcelium rejects it. Concrete-per-instance preserves the "one file you edit" workflow.
- Fail-closed validation: `instances` requires `parameters`; instance names are unique
  legal SV identifiers; `values` reference declared parameters; a focused slice —
  single-agent bench, no `analysis` (each instance already gets its scoreboard).
- Validated on `examples/twowidth/`: one VIP → an 8-bit and a 16-bit datapath, each
  checked by its own scoreboard, **51/51 each on Xcelium** (0 errors). verible-lint-
  clean; CI gates it.

**Status — first slice landed (parameterized VIP machinery):**
- `parameters:` on an agent (e.g. `{name: W, default: 8}`) make its interface AND all
  its UVM classes `#(...)`-parameterized (transaction, driver, monitor, sequencer,
  agent, cfg, cover, sequences — with `uvm_*_param_utils` and a parameterized
  `virtual <if>#(W)` / `config_db`). Port widths reference a parameter via
  `width_param: W` (`logic [W-1:0]`). The env/top instantiate the VIP at concrete
  default values (`io_agent#(8)`, `virtual io_if#(8)`), and the scoreboard types on
  the parameterized transaction (`io_seq_item#(8)`). **Opt-in: an agent with no
  `parameters` is byte-identical** (verified zero diffs across all examples).
- Fail-closed validation: `width_param` names a declared parameter and is scalar-only
  (no enum/struct/packed); parameter names are unique/legal SV identifiers.
- Validated on `examples/pwidth/`: the parameterized VIP compiles and runs on Xcelium
  at **W=8 and W=16 (51/51 each)** — genuinely width-flexible, not fixed. verible-lint-
  clean; CI gates it.
- *Landed in the next slice:* `instances:` — two instances of the VIP at different
  widths in **one** bench (see the multi-instantiation status block above).

### H1 — Sub-environments — DONE (first slice)
`subenvs:`; nest child env packages + configs + param propagation. Depends F1/F2/C1/C3.
**Accept:** a subsystem env composes ≥2 block envs. ✅

**Status — subsystem composition landed:**
- `subenvs:` makes a bench a subsystem (top) that composes ≥2 child block envs. Each
  child is referenced by config path (`{name: adder, config: adder/adder.yaml}`),
  resolved relative to the top file; the loader reads each child bench config and
  cross-checks the composition (unique block/agent/interface/transaction names — the
  blocks share one output dir + package namespace).
- Each child's **reusable env layer** is generated (its agent VIP `<agent>_pkg` +
  `<block>_env_pkg`) with no test/top/clkgen/DUT-stub, and the **top layer** composes
  them: a `<top>_env` instantiating each `<block>_env`, a `<top>_virtual_sequencer`
  collecting each block's agent sequencer, a `<top>_vseq` firing every block's default
  sequence concurrently, a `<top>_base_test` that populates each child env config (agent
  cfgs + vifs) and hands it down, and a `tb_top` instantiating each block's interfaces +
  real DUT. Each block keeps its own scoreboard checking its own DUT.
- **Opt-in: a bench with no `subenvs` is byte-identical** (a dedicated composition path;
  the ordinary-bench flow is untouched). Fail-closed guards: `subenvs` require
  `layout: packaged`, no own `agents`, ≥2 blocks, unique subenv names, and (this slice)
  no nested subenvs / register-model child.
- Validated on `examples/soc/`: one subsystem composing an `adder` block (dout=din+1)
  and an `inverter` block (dout=~din), driven concurrently by the top vseq — **31/31 on
  each block's scoreboard on Xcelium** (0 errors). verible-lint-clean; CI gates it.

**Status — parameter propagation landed:**
- A subenv can override its (parameterized) block's agent parameters for that instance:
  `{name: dp, config: dp/dp.yaml, params: {W: 8}}`. The override is baked into the child
  agent's parameter default before generation, so the block's whole env — VIP classes,
  scoreboard, interface and DUT — is generated/instantiated at that width (reusing the
  C3 machinery). The top threads the concrete `#(W)` into the interface/DUT/config_db
  (`d_if#(8)`, `dp#(8)`), the top virtual sequencer (`d_sequencer#(8)`), the top vseq
  (`d_seq#(8)`), and the base test's cfg/vif. Byte-identical for non-parameterized blocks.
- Fail-closed: an override must name a declared block parameter; a parameterized child
  block must be single-agent (the DUT `#()` args come from the sole agent).
- Validated on `examples/psoc/`: a subsystem composing two **parameterized** blocks
  propagated to different widths — `dp` at W=8 (dout=din+1) and `mac` at W=16
  (dout=din<<1) — **31/31 on each block's scoreboard on Xcelium** (0 errors), from the
  same reusable width-parameterized block configs. verible-lint-clean; CI gates it.
**Status — cross-block scoreboards landed:**
- A subsystem can wire composed blocks into a pipeline and check them across the
  boundary. `connections: [{from: add.dout, to: inv.din}]` emits the top-level wire
  (a source block's output drives a destination block's input); the destination
  block's agent is passive on that port (its input is a monitored, externally-driven
  signal — QuickUVM emits it as a sampled clockvar and the passive driver drives
  nothing, byte-identical for existing benches). `subenv_scoreboards: [{name: chk,
  source: add.a, monitor: inv.b}]` generates a cross-block scoreboard reusing the A2
  two-stream in-order predictor/comparator, sourced from two different blocks: it
  predicts the monitor block's output from the source block's stream and compares.
- Fail-closed: `connections`/`subenv_scoreboards` are subsystem-only; endpoints must
  resolve (`block.port` / `block.agent`); a connection's destination-block agent must
  be passive; a scoreboard's source and monitor must differ; scoreboard names unique.
- Validated on `examples/pipe/`: a two-stage pipeline — add (dout=din+1) feeds inv
  (dout=~din) through an auto-generated connection — with the cross-block scoreboard
  checking `inv.dout == ~(add.dout)` **plus** each block's own scoreboard: all three
  pass **31/31 on Xcelium** (0 errors). verible-lint-clean; CI gates it.
**Status — same block reused at N widths landed:**
- The SAME parameterized block config can be composed more than once in one subsystem
  at different values. QuickUVM detects a shared `config` path (referenced by >=2
  subenvs) and auto-namespaces each instance's classes by its subenv name — it prefixes
  the loaded child's `dut.name` + each agent's `name`/`interface`/`sequence_item`/
  sequence names, which cascades through existing generation to give fully distinct
  class/file/package sets (`lo_chan_env`, `lo_c_seq_item#(8)` vs `hi_chan_env`,
  `hi_c_seq_item#(16)`). The reused RTL DUT module stays UNprefixed (both instances
  reuse one `chan` module, instantiated `chan#(8)` / `chan#(16)`).
- Simple by default, powerful when needed: `namespace` on a subenv overrides the
  auto behavior — `true` forces prefixing by the subenv name, a string forces a custom
  prefix, `false` disables it (a genuine collision then fails closed). A config used
  once is never namespaced (soc/psoc/pipe byte-identical).
- Fail-closed (this slice): a namespaced (reused) block may not be referenced by a
  cross-block `connection`/`subenv_scoreboard` (the endpoint agent names are prefixed).
- Validated on `examples/channels/`: one `chan` block config composed at W=8 and W=16,
  each auto-namespaced and self-scoreboarded — both pass **31/31 on Xcelium** (0 errors)
  from one config + one RTL module. verible-lint-clean; CI gates it.
**Status — nested subenvs landed (H1 feature complete):**
- A subenv may itself be a subsystem — a top composes clusters, each cluster composes
  leaf blocks (arbitrary depth; the loader + generation + config-db walks are all
  recursive). Composition is HIERARCHICAL: the top's virtual sequencer holds each
  cluster's vsqr and the top vseq forks each cluster's vseq; a cluster's vsqr holds its
  leaf agents' sequencers and its vseq forks their sequences. The base test builds the
  full env-config TREE (each level's cfg set into the config DB at its absolute path
  `e.<cluster>.<leaf>`, leaf agent cfgs + vifs by full-path key), and each env
  self-configures its direct children. tb_top instantiates every LEAF block's interface
  + real DUT (flattened, path-prefixed names); the reused leaf RTL module stays
  unprefixed. The top test package imports every leaf package and includes each level's
  composition classes (deepest-first).
- Fail-closed (this slice; later slices lifted these): cross-LEVEL connections/
  scoreboards, `params` on a nested subsystem, and namespacing (reusing) a nested
  subsystem were rejected; every subsystem/block/agent/interface/transaction name must be
  unique across the flattened tree. Byte-identical for flat single-level subsystems.
- Validated on `examples/nested/`: a 3-level hierarchy — top `nested` composes
  `clusterA` + `clusterB`, each composing two leaf blocks — driven top→cluster→leaf,
  each leaf self-scoreboarded: all four leaves pass **21/21 on Xcelium** (0 errors).
  verible-lint-clean; CI gates it.

**Status — parameterized / reused nested subsystems landed:**
- A whole nested subsystem (cluster) can now be REUSED (composed >=2x → auto-namespaced)
  and/or PARAMETERIZED. Both are single recursive model transforms: the namespace prefix
  and the `params:` override are applied down the ENTIRE cluster subtree (stacking on any
  inner prefix), so the same cluster reused twice yields collision-free class sets and the
  width reaches every grandchild agent. The reused leaf RTL module is recovered UNprefixed
  (the original dut.name is captured once, before any prefix, so it survives stacking).
- Fail-closed still: a `params:` key that no descendant agent declares; cross-level into a
  REUSED (namespaced) subtree (a distinct follow-up). Byte-identical for every
  non-reused/non-parameterized path (the recursion is a no-op when the prefix is "" and
  there are no params).
- Validated on `examples/nsoc/`: the SAME parameterized `chan` cluster (adder + shifter)
  composed twice — lo at W=8, hi at W=16 — auto-namespaced (lo_*/hi_*) with the width
  propagated to every leaf; all four leaves pass **21/21 on Xcelium** (0 errors). verible-
  lint-clean; CI gates it.

**Status — cross-LEVEL connections / scoreboards landed:**
- A connection/scoreboard endpoint may now be a dotted PATH reaching a LEAF block inside a
  nested subsystem (`stg1.add.dout`), resolved RELATIVE to the level that declares it
  (any level may declare — the top for a cross-cluster wire, a cluster for its own). One
  path-walk resolver (`_resolve_endpoint`) feeds both features; a same-level `add.dout` is
  a 1-segment path, so the flat `pipe` bench stays byte-identical.
- WIRES surface as flattened tb_top assigns: `tb_top` gathers EVERY level's connections
  (`all_resolved_connections`), each resolved to its full path-prefixed interface instance
  (`stg1_add_a_if_inst.dout`) — the physical signal the flatten machinery already
  instantiates. SCOREBOARDS emit at their declaring env with a dotted child-env handle
  chain (`stg1.add.a_agnt.ap`), reachable because each child env is a handle named for the
  subenv.
- Fail-closed: an endpoint naming a subsystem directly (not a leaf), descending into a
  leaf, or an unknown segment. Single-driver is keyed tree-globally on the canonical
  resolved destination (a leaf input driven by wires at two different levels is caught).
- Validated on `examples/xpipe/`: a top wire reaches into two clusters
  (`stg1.add.dout -> stg2.inv.din`) and a cross-level scoreboard predicts `inv.dout =
  ~(add.dout)` across them; all five scoreboards (four leaf self-checks + the cross-level
  `xchk`) pass **31/31 on Xcelium** (0 errors). verible-lint-clean; CI gates it.

**Status — cross-level into a REUSED (namespaced) subtree landed:**
- A cross-level endpoint may now descend into a reused subtree. The path uses subenv
  INSTANCE names (which reuse preserves — `left.src`), so it disambiguates the reuse
  instance for free; only the trailing agent token needed work. It is the agent's
  ORIGINAL name (`sa`), captured once in `_apply_namespace_prefix` (`AgentConfig.
  original_name`, like `original_dut_name`) so the prefix stays a fully internal
  artifact — the config reads identically to a non-reused cross-level bench. Wires
  needed nothing beyond lifting the guard (ports are never mangled, and the resolved
  leaf agent's already-prefixed interface yields the exact `left_src_left_src_if_inst`
  tb_top instance); scoreboards map `sa`→`left_sa` for the `left.src.left_sa_agnt.ap`
  handle.
- Validated on `examples/dsoc/`: the SAME `lane` cluster (src + snk) reused twice
  (left/right, auto-namespaced) and ring-wired across the hierarchy — each lane's src
  drives the OTHER lane's snk, with two cross-level scoreboards checking each sink; all
  six scoreboards pass **31/31 on Xcelium** (0 errors). verible-lint-clean; CI gates it.

**H1 is feature-complete** — every cross-cutting combination now works: composition,
parameter propagation, cross-block scoreboards, same-block reuse, nested subsystems,
parameterized/reused nested subsystems, cross-level connections/scoreboards, and
cross-level into a reused subtree.

### P0 — `inout` / tri-state / open-drain ports — DONE
A third port category, `inouts:`, completing the SV direction keywords
(`inputs`/`outputs`/`inouts` <-> `input`/`output`/`inout`). Neither TB-driven nor DUT-driven
can express a net that must be **released**. Unblocks I2C and every bidirectional bus.
**Accept:** a bidirectional open-drain bus generates, and a multi-driver collision is caught. ✅

**Status — landed:**
- `ports.inouts: [{name, width, open_drain, pullup}]`. Each yields THREE transaction fields:
  `<n>_o` (what we drive), `<n>_oe` (whether we drive — **releasing is a first-class choice**)
  and `<n>` (the **RESOLVED** line, sampled; never what we drove).
- The interface emits a `wire` (resolved from both sides) + the drive/enable pair.
  `open_drain` means **driving a 1 IS releasing** — the line can never be driven high, which
  is exactly why two devices may pull low at the same instant with no contention.
- **`pullup` is mandatory with `open_drain`, and that is not a style preference:** with no
  pullup the line floats to **X** the moment everyone releases and every downstream sample is
  silently poisoned. Emitted as `assign (weak1, weak0) <n> = '1;` — **not** a `pullup`
  primitive, which is *illegal inside an interface* (`*E,INFINS`).
- The driver **releases every shared line at time 0** (a TB that drives before it has anything
  to say fights the DUT and both ends read X). The monitor samples the line **with the DUT
  outputs** — a shared line and both drivers' states must be observed at the SAME INSTANT.
- Coverage may target the synthesised fields: `<n>_oe` ("who is holding the line?") is usually
  the most interesting coverpoint on a shared bus.
- Fail-closed: `open_drain` requires `pullup` and width 1; a name may not appear in both
  `inouts` and `inputs`/`outputs`; a declared port may not collide with a synthesised
  `<n>_o`/`<n>_oe`. Opt-in + byte-identical (the 31-example gate is unmoved).
- Validated on `examples/odbus/`: **62/62 on Xcelium**, self-checking against the **wired-AND
  contract**, and mutation-proved both ways a tri-state contract can break — a DUT that drives
  HIGH instead of releasing (contention) fails 10/62, and removing the pullup (floating X)
  fails 37/62.
- **The first version silently passed both mutations**: it predicted the resolved line and then
  never compared it. Four bugs were hiding behind that green bar — `do_compare` skipped the
  line, the DUT was never connected in `tb_top` (TB and DUT on *different wires*), the line was
  sampled a cycle out of step with the DUT's drive state, and `do_copy` dropped the drive state
  so the predictor modelled a bus nobody was driving. Each now has a regression test.
- *Deferred:* per-bit open-drain on a vector (declare one port per line); `inouts` on a
  responder agent; bus-keeper / weak-pull-down variants.

### Sampled clock — a clock the TB observes but does not generate  *(new)*
Every QuickUVM clock comes from a generated `clkgen`. But a device agent's clock is a **DUT
output** (SPI `SCK`, I2C `SCL`) — the TB samples it and must never drive it. M1 has no concept
of this. Small, and it rides on the reactive-agent work for free.

### UART baud-divisor driver timing  *(new, small)*
Driver bit-timing derived from a **CSR-programmed** baud divisor + 16× oversampling — i.e.
driver timing as a function of a *register value* rather than a clock edge. Harvested from the
`uart` target, which was otherwise rejected as uninformative (its driver is initiator-only, so
it would merely re-prove `rv_timer` with a serial wire bolted on).

### Reactive / responder (device) agent — DONE
A per-agent **reactive** mode: the DUT initiates and the agent RESPONDS (an SPI device, a
memory slave, an I2C target). Closes the architectural gap the OpenTitan comparison flagged,
and is the long pole for campaign target **T2** (`spi_host`).
**Accept:** a `mode: responder` agent answers a DUT master and is checked by a scoreboard. ✅

**Status — landed (both responder shapes):**
- `mode: initiator | responder` + `request_valid` (the sampled port meaning "the DUT issued a
  request"). **The port-direction model is UNCHANGED**: a device agent still drives the DUT's
  `inputs` (now the RESPONSE) and samples its `outputs` (now the REQUEST). Only the timing and
  the sequence change.
- **Two shapes, and the difference is forced by the protocol, not taste** (verified at source in
  `uvma_obi_memory_drv.sv`, not from a survey summary):
  - **blocking** (no `idle:`) — `get_next_item` → drive → `item_done`. **The driver loop is the
    initiator's, unchanged** — the load-bearing simplification. (OpenTitan `dv_reactive_agent`,
    Verilab SNUG-2016.)
  - **continuous** (`idle:` present) — the DUT samples our outputs *every* cycle, so parking
    would leave them stale or X. Non-blocking `try_next_item` + `drive_idle()` on a miss.
    (OpenHW OBI, CESNET OFM.) **The knob is the DATA**: declaring `idle:` *is* the statement
    "this bus has a per-cycle obligation", and it carries exactly what that shape needs. A
    separate `driver_style:` flag would be redundant — and redundant knobs are how a schema
    starts lying.
- Reactivity lives in the **monitor** (a second `request_ap`, published on `request_valid`), the
  **sequencer** (a `uvm_tlm_analysis_fifo` giving a blocking rendezvous), and a **forever
  responder sequence** — *not* in the driver. The monitor already decodes the protocol for
  passive mode, so nothing is duplicated. The tempting driver-decodes design is rejected.
- **The agent OWNS its responder** and forks it in `run_phase`. It is *not* a phase
  `default_sequence`: a phase sequence is **killed when its phase ends**, and a responder raises
  no objection (it is a service, not stimulus), so it would be torn down instantly unless
  something else kept that phase alive. Verilab's guidance assumes the test's vseq keeps
  `main_phase` alive (true in OpenTitan's cip_lib, **false** for a generated bench using
  `run_phase`). *This was gotten wrong first, and the bench "passed" while the device never
  answered — which is why the example ships a scoreboard rather than trusting a green bar.*
- **The test never starts stimulus on a responder's sequencer** — its forever sequence owns it,
  and a second sequence there would clobber the computed responses with random items (again:
  observed, not theorised).
- The per-cycle protocol thread (a combinational grant, say) is a **pragma seam**
  (`driver_threads`), never generated — *no generator emits protocol logic*.
- Fail-closed: responder ⇒ `active: true` (reactive is **not** passive), ≥1 driven port,
  `request_valid` names a 1-bit SAMPLED port; `idle` keys name DRIVEN ports and fit their widths;
  both rejected on an initiator. Opt-in + byte-identical (the 30-example gate is unmoved).
- Validated on `examples/memslave/` (a DUT that fetches from a TB-side memory): **34/34 on
  Xcelium**, self-checking, and mutation-proved **against the responder itself** — a device that
  answers wrong data fails 31/34, and a device that never answers at all fails with
  `DEAD_RESPONDER`/`NO_PROGRESS`.
- **A pre-merge adversarial review found the first self-check was a tautology**: it derived the
  expected value from the `rdata` observed on the bus, so a responder mutated to never grant left
  the DUT wedged with zero transfers and the bench still reported **PASS 34/34**. The scoreboard
  now predicts from the request ADDRESS via its own memory model, and a `check_phase` asserts
  liveness (a dead responder cannot be caught per-transaction: with no grant, expected and actual
  are both zero and every compare agrees). The review also closed four more paths that let random
  stimulus reach a responder's sequencer (`test.sequence`, C3 `instances`, H1 subenv vseqs, and
  the test's branch order), fixed a level-vs-edge request publish that made the responder answer
  the same request every cycle it was held, made `initialize()` park at the declared `idle:`
  values, and gave the responder factory context (without which the advertised
  swap-in-an-error-injector override silently no-opped).
- *Deferred:* the `mem_model` primitive; pipelined/out-of-order responders (`put_response` /
  `set_id_info`); an `if_mode`-style host/device driver swap within one agent.

### Reactive / responder agent — the original investigation
A per-agent **reactive** mode: the driver responds to DUT-initiated transfers (a
device/slave/target) instead of proactively initiating. Surfaced as an architectural
gap by the OpenTitan comparison + [`maturity_assessment_rv_timer.md`](maturity_assessment_rv_timer.md)
(the rv_timer interrupt was modeled as a *monitored* signal, not a true device agent).
A Phase-1 industry investigation is written up in
[`reactive_agent_investigation.md`](reactive_agent_investigation.md): the recommended
architecture (Verilab SNUG-2016 / OpenTitan `dv_reactive_agent`) puts reactivity in a second
monitor analysis port + a sequencer `uvm_tlm_analysis_fifo` + a *forever* responder sequence,
so QuickUVM's `input_ports`/`output_ports` split already fits. Proposed minimal schema
(`mode: initiator|responder` + `request_valid`), the response-logic pragma seam, the
byte-identity story, and the effort/deferrals are in that doc.

> **⚠ The design doc is PARTLY WRONG — fix it before building.** Its headline claim ("the
> driver stays unchanged") holds for OpenTitan/Verilab but is **false for OpenHW OBI and
> CESNET OFM**, whose slave drivers are **non-blocking** (`try_next_item()` + a grant task)
> and **idle-drive every cycle** — because a slave that drives only when it holds an item
> leaves the bus at **X**. The `mode:` schema must express the blocking *and* the
> non-blocking responder, or it is under-specified. Five industrial idioms are tabulated in
> [`reproduce_campaign.md`](reproduce_campaign.md) §1.1.

**Not yet scheduled** — but it is the long pole for the `spi_host` campaign target (T2), and
worth building regardless.
**Accept (when built):** a `mode: responder` agent responds to a DUT master and is
checked by a two-stream (A2) scoreboard on a real bench.

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

### K1 — Assertion / protocol-checker scaffolding — DONE
Generate interface-level SVA scaffolding — a sample protocol property + a user-SVA hook
pragma — so a generated bench ships with checking structure (the protocol properties are
user code; the binding/structure is scaffolded).
**Accept:** an `*_if` emits a sample property + a user-SVA hook. ✅

**Status — landed (in-interface, opt-in):**
- Per-agent `assertions: true` (`AgentConfig`, byte-identical when `False`) makes that
  agent's interface carry a sample SVA property plus a `sva_properties` pragma region for
  the user's own protocol assertions. The sample asserts the first output is never X/Z
  once reset deasserts (`!$isunknown(<out>)` with `$error`, no UVM dependency in interface
  scope), gated at the agent's OWN reset polarity: `disable iff (!<rst>)` active-low,
  `disable iff (<rst>)` active-high (resolved from `agent_reset` / `agent_driven_reset`).
  A combinational / no-reset agent ships the pragma scaffold only (a live `$isunknown`
  would fire at t=0).
- Design: the SVA lives INSIDE the interface (no `bind`, no extra file, no top.sv/run.f
  change) — chosen over a separate bound module because, riding inside the interface that
  is already instantiated everywhere, it is correct **for free** across multi-clock
  (samples on the interface's own `clk`/reset), C3 parameterization, and H1 composition,
  with zero bind machinery. (A separable bound-checker module remains a possible follow-up.)
- Validated on `examples/dualreg/` — both agents opt in, exercising active-low (`a_rst_n`)
  AND active-high (`b_rst`) in one bench: **Xcelium exit 0, UVM_ERROR/FATAL/WARNING all 0**,
  assertions live. Byte-identical when off (the 26-example byte-identity gate is unmoved);
  verible-lint-clean; CI already lints `dualreg` + gates byte-identity.

### K2 — Whitebox spy/probe observation — DONE  *(builds on K1)*
OBSERVE-only access to INTERNAL DUT signals (FSM state, FIFO levels, internal
handshakes) for coverage / checkers / debug — without exposing debug ports. Black-box
observation stays the default; whitebox is strictly opt-in.
**Accept:** a `probes:` entry taps an internal signal (invisible at the DUT ports) that
is asserted + covered in the TB and passes on the CI simulator; a wrong *internal*
encoding is caught. ✅

**Status — landed (XMR + probe interface + passive probe monitor):**
- Mechanism = **hierarchical reference (XMR)**, chosen over `bind` and `uvm_hdl` after a
  deep survey ([`whitebox_observation_investigation.md`](whitebox_observation_investigation.md)).
  XMR uniquely matches the "one exact path
  per net" data model of the Architect extension, is **fail-closed at elaboration** (a
  wrong/renamed path is a compile error, not a silent miss), is the **most portable**
  (the only door that works on Verilator; `uvm_hdl` is fail-OPEN and Verilator-less), and
  reuses QuickUVM's existing interface + `config_db` + K1-SVA machinery. *bind rejected:
  the schema is path-from-DUT-instance, not (module-type, local-signal); multi-instance
  clobbers one `config_db` key; Verilator can't bind to instance paths. uvm_hdl rejected:
  fail-open + no Verilator — it stays the register-backdoor door only.*
- Top-level `probes: [{name, path, width|enum|type|struct|real, clock?, coverage?}]`.
  `path` is relative to the DUT instance; the generator emits `assign probe_if.<name> =
  dut_inst.<path>;` (never `force`). The observed field reuses the S1 type machinery, so
  an enum FSM gets **symbolic** coverage (the monitor `$cast`s the raw bits); a `real`
  probe is SVA-checkable but carries no `coverage` (SV forbids a real coverpoint).
- Fail-closed validation: legal SV identifiers; non-empty path; unique names; no
  collision with agent port / interface / clock / reset nets; `clock` names a declared
  clock (default the sole/first); a single probe clocking domain (multi-domain deferred);
  probes rejected with `subenvs` (H1 — per-leaf DUTs) and with `instances` (C3 — no single
  DUT), each with a follow-up note.
- Validated on `examples/wbx/`: a FIFO block whose internal `fill_level` / FSM `state` /
  `real acc` are invisible at the ports — probed, asserted (`probe_sva`), and covered
  (numeric + symbolic). **Xcelium exit 0, 0 warn/err**; and a **mutation proof** — an FSM
  that declares `FULL` one slot early makes the probe SVA `a_full_max` **fire** and fail
  the sim, catching a wrong internal encoding. Byte-identical when absent (the byte-identity
  gate is unmoved); verible-lint-clean.
- *Deferred:* multi-clock-domain probes (one probe clocking block for now); probes under H1
  composition (path prefixing) and C3 multi-instantiation; a `bind`-by-type observer for
  "every instance of a repeated sub-block."

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

### M1 — Multi-clock / multi-reset — DONE
Promote `clock`/`reset` to lists; per-agent clock association; multiple clock-gens + reset
generators. Needed for CDC and most real SoC blocks.
**Accept:** a 2-clock-domain bench generates and runs. ✅

**Status — flat multi-clock / multi-reset landed:**
- `clock:` accepts a single mapping (today, byte-identical) OR a **list** of named
  domains — a before-validator splits a list into `clock` (the primary, for every legacy
  single-clock read + the `-timescale`/scoreboard unit) and `clocks` (the full list);
  `effective_clocks` returns `[self.clock]` for a single-clock bench, so it stays
  byte-identical. A new `resets:` list (each `ResetConfig` = name + polarity + a `clock:`
  it deasserts synchronously to; no clock ⇒ async) generalizes the single external reset,
  which `effective_resets` synthesizes from `dut` when the list is empty.
- Each agent names its domain via `clock:`/`reset:` (None ⇒ the sole/first clock + its
  reset). The generator resolves a per-agent clock/reset **view** that equals the global
  clock / `dut.reset` for a single-domain bench, so the agent templates (interface skew,
  driver/monitor reset-gate) render byte-identical. `clkgen` is parameterized
  `#(int PERIOD)` (single-clock branch kept textually identical) and instantiated once per
  domain; `tb_top` branches to a multi-domain body (N clock nets + clkgens, N reset
  generators each synced to its clock with its own pragma region, per-agent interface
  binding) while the single-domain body is the verbatim legacy path.
- Fail-closed: an agent/reset naming an undeclared clock or reset; a reset name colliding
  with a clock net; multi-domain combined with a multi-instantiated agent (`instances`) or
  with `subenvs` (clocked-subenv composition is the deferred H1 lift).
- Validated on `examples/mclk/`: a two-clock-domain DUT (clk_sys @10, clk_io @6) with one
  external reset per domain and a self-checking scoreboard per lane — both lanes pass
  **on Xcelium** (0 errors). verible-lint-clean; CI gates it.
- **Mixed-unit `-timescale` landed:** clocks may use different time units — the tb emits
  ONE `-timescale` at the finest unit across the clocks (`timescale_unit`) and scales each
  clock's period + the clocking-block drive skew into it (`clock_period_ts`), so a 500 ps +
  10 ns bench emits `-timescale 1ps/1ps` with `clkgen #(500)` / `#(10000)` and the slow
  lane's skew `#2000`. A scoreboard latency literal uses the monitor lane's own unit.
  Single-unit benches are byte-identical (the finest unit is that unit; nothing scales).
  Validated on `examples/mxclk/` (500 ps + 10 ns lanes, self-check each) — **2/2 on
  Xcelium**; unknown units in a mixed set are rejected. verible-lint-clean; CI gates it.
- **Clocked-subenv composition landed (H1 x M1):** the H1 combinational-only guard is
  lifted — a subsystem may now compose CLOCKED leaf blocks. Each clocked leaf becomes its
  own M1 lane: the flattened `subenv_top` generates a pathname-prefixed clock net + reset
  net, its own parameterized `clkgen #(period)`, and a reset generator synced to that
  leaf's clock (its own pragma region), and binds each interface + DUT + reset-gates each
  driver/monitor to its leaf's domain. The **entire leaf VIP layer was already
  clocked-ready** in subenv mode (the M1 per-agent view flows into leaf generation
  unconditionally), so the slice is almost purely `subenv_top` physical wiring + the guard
  lift + `LeafView` clock/reset accessors. Leaf-driven (each leaf declares its own
  clock/reset; the top stays combinational — no new top schema); the top owns the reset
  generators. A fully COMBINATIONAL subsystem is byte-identical (the clock/reset block is
  gated on any-clocked-leaf). Fail-closed: a composed clocked leaf must be single-clock /
  at-most-one-reset and share the subsystem's time unit. Validated on `examples/csoc/`:
  two clocked leaves at DIFFERENT periods (acc @10 ns + mul @8 ns) — two independent clock
  domains in one subsystem, each self-checking — pass **2/2 on Xcelium** (0 errors).
  verible-lint-clean; CI gates it.
- **Multi agent-driven resets landed (M1 complete):** the AGENT-DRIVEN reset path (the
  reset is an agent input port its sequences drive, vs a top-generated external reset) is
  now PER-AGENT and polarity-correct. A new `AgentConfig.reset_port` names which of the
  agent's own input ports it drives as reset (unset ⇒ falls back to the port named
  `dut.reset`, byte-identical); `reset_port_active_low` overrides the global polarity per
  agent. One resolver `agent_driven_reset(agent)` (name + polarity, or None on the
  external/combinational path) threads through the six agent-driven sites (driver park,
  default sequence + seq-library constraints ×4, cover bins, monitor re-sample, reference
  model), each gated so an active-low single-reset bench (`simple_reg`) is byte-for-byte
  identical. This ALSO fixes a latent bug: driver-park / seq-constraint / cover-bins
  hardcoded the active-*low* literals, so an active-high agent-driven reset generated wrong
  stimulus. Fail-closed: a `reset_port` that isn't the agent's own input port, combined
  with `dut.external_reset`, or combined with M1 `clock:`/`resets:` lists. Validated on
  `examples/dualreg/`: two registered lanes, each reset by its own agent at OPPOSITE
  polarities (a active-low + b active-high) — both self-check and pass **2/2 on Xcelium**
  (0 errors). verible-lint-clean; CI gates it.
- *Deferred:* per-domain scoreboard latency across two differently-clocked streams;
  multi-domain with `instances`; mixed-unit / nested-multi-clock clocked leaves;
  agent-driven resets combined with M1 multi-clock domains; a dedicated assert-then-
  deassert reset sequence-kind body.

### R1 — Regression & coverage infrastructure — DONE  *(the last item on the v1.0 list)*
Per-simulator makefiles, a testlist/regression runner, seed management, and a
coverage-merge flow (coverage closure needs all of these).
**Accept:** `make regress` runs N tests × M seeds and merges coverage. ✅

> **This does NOT declare v1.0.** The roadmap list is complete; the *release* is not.
> The version stays **0.9.x** pending intensive testing — and R1 exists precisely to make
> that testing possible (tests × seeds, merged coverage, reproducible failures). Every
> feature here has been validated on its own example; what has *not* happened yet is
> sustained multi-seed regression across the whole example suite, which is exactly the
> kind of exercise that turns up single-seed artefacts. Bump to v1.0 only on the far side
> of that.

**Status — landed (opt-in `regress:` → a generated Makefile):**
- `regress: {simulator, filelist, seeds, coverage}` → QuickUVM emits a
  **`Makefile`** next to the generated sources: `help` / `build` / `run` / `regress` /
  `cov` / `clean`. It **elaborates once** (`xrun -elaborate` → a snapshot) and runs the
  whole matrix against it with `xrun -R`, so N×M runs cost one elaboration.
- **The testlist is derived, not restated**: `tests[]` + the RAL `reg_test` + one test
  per C5 `csr_tests` kind (`ProjectConfig.regress_jobs`). Per-test `seeds:` overrides
  `regress.seeds` (the one idea worth stealing from OpenTitan's dvsim `reseed`).
  *Trap encoded in the model:* the RAL basic test's **class** is the bare `reg_test` —
  only its *file* is `<dut>_reg_test.svh`. A testlist that assumed the `<dut>_` prefix
  would hand `+UVM_TESTNAME` an unregistered name.
- **Seeds are explicit and recorded** (`SEED_BASE..SEED_BASE+n-1`, written to
  `seed.txt`, passed as `-svseed`), never `-svseed random`: a regression you cannot
  replay is not a regression. Every failure prints `reproduce: make run TEST=<t> SEED=<s>`.
- **The verdict does not trust the exit code.** `xrun` exits **0 even with UVM_ERRORs**,
  and `Number of caught UVM_ERROR reports` is the report-*catcher* count (always 0) —
  parsing either marks failing runs PASS, silently turning a red regression green. The
  runner parses the `** Report counts by severity` block **and** requires `Simulation
  complete via $finish` (a crash never prints the block at all).
- Coverage: `-coverage all` at elaborate (instrumentation), `-covtest <test>.<seed>` per
  run (bookkeeping — a `-coverage` flag on a `-R` run is *silently ignored*), then `imc`
  merge + text report. `imc`'s `-batch`/`-exec`/`-execcmd` are mutually exclusive
  (`-batch -exec f` silently does nothing), so the recipe writes a command file and
  passes it to `-exec` alone; `report_metrics` is HTML-only, so the text summary uses the
  legacy `report -summary -text`. `regress` drops the previous run's per-test coverage
  DBs first, so the merged number can never fold in an older regression's runs.
- **The snapshot is rebuilt when its sources change** (the stamp depends on the filelist
  and the files it lists). Without that, an RTL edit would silently re-run the *old*
  snapshot and report PASS — the same false-green class as trusting the exit code.
- Opt-in + byte-identical when absent (no `regress:` ⇒ no Makefile ⇒ the 28-example
  byte-identity gate is unmoved). Fail-closed: seeds ≥ 1, goal 1..100, goal requires
  coverage, non-empty filelist, no duplicate `+UVM_TESTNAME`, and `subenvs` rejected (a
  subsystem's leaf RTL lives in a pragma region, so the real filelist can't be derived).
- **Xcelium-only, deliberately.** It is the simulator every example is validated on and
  the merge recipe (`imc`) is tool-specific; a Questa/VCS branch that ships untested is
  worse than none. Site flags go in the `extra_make_vars` / `extra_make_targets` pragma
  regions (the merger already accepts `#` markers — no merger change needed).
- Validated on **`examples/rvtimer/`** (5 tests × seeds = **9 runs, 9/9 on Xcelium**,
  coverage merged: `host_cov` 100% (17/17), DUT block 100%) and **`examples/alu/`** (3
  seeds, **3/3**). **Coverage merge proven to accumulate**: 43/88 bins from seed 1 alone
  → **47/88 merged across 3 seeds**. **Mutation proof**: a one-line error injected into
  the golden model turns 5/9 runs **FAIL** with reproduce commands and a **nonzero exit**
  — while `xrun` itself exited 0 on every one of them.
- *Deferred:* a **coverage `goal:` gate** (fail the regression below N%) — it needs a
  defensible single number to gate on, and imc's text summary is a per-instance table of
  several metrics; "the first percentage in the report" is not a coverage target, and a
  gate that silently doesn't apply is worse than none. The covergroup-level target already
  exists (V1 `coverage_models[].goal` → `option.goal`). Also deferred: subsystem (H1)
  regressions; Questa/VCS branches; a `regressions:` grouping (`make regress JOBS="a:1 b:2"`
  covers it); parallel runs default to `JOBS_N=1`.
- *Adversarially reviewed* (30 agents, 22 confirmed findings — all fixed or cut). The ones
  that mattered were all the same species: **a regression that cannot go red.** Stale
  snapshot after an RTL edit; a stale `sim.log` verdicted when `xrun` fails to *launch*;
  merged coverage folding in a previous regression's DBs; `xargs` without `-r` turning an
  empty testlist into "1/1 passed"; a `0/0 passed` exiting 0; the coverage goal failing
  *open*. Each now has a regression test.

### The Xcelium-in-CI gate — what it actually turned out to be
The empirical assessment found a latent generator bug — the `analysis.coverage:` path
emitted `<agent>_cov <agent>_cov;` (member == type) and then `<agent>_cov::type_id::
create()`, which verible accepts but Xcelium **rejects at compile** (`*E,NOPBIND: Package
<agent>_cov could not be bound`). The roadmap called for "a minimal Xcelium smoke in CI."
**That is not available to us**: CI runs on GitHub-hosted runners, which have no Cadence
licence. Measured against the actual bug:

| gate | buggy code | clean code | verdict |
|---|---|---|---|
| `xrun -compile` | exit 1 | exit 0 | the only discriminator (seconds) |
| verible-verilog-lint (CI today) | exit 0 | exit 0 | **blind** |
| verilator `--lint-only` | exit 0 | exit 0 | **also blind** |
| iverilog `-g2012` | errors | **errors** | false-positive machine |

So a free-simulator lane cannot substitute. What shipped instead, both mutation-proved:
1. **`tests/test_no_type_shadowing.py`** (+ `quick_uvm/svcheck.py`) — a targeted static
   check, free on hosted CI, **ENFORCED**. The invariant is deliberately **narrow**: a
   member shadowing its type is only fatal when a bare `<type>::` also appears *in the
   same class scope*. A shadowing declaration alone is legal, and QuickUVM ships ~43 of
   them (`<agent>_cfg <agent>_cfg;` in every `*_env_cfg.svh`) — the naive "member != type"
   rule the roadmap literally asked for would fire on all 43, forcing a mass rename that
   breaks byte-identity for **zero** safety.
2. **`scripts/xrun_gate.sh`** — the real compiler (`xrun -compile`) over all 28 examples,
   catching bug classes we haven't thought of. Needs a licence, so CI **cannot enforce
   it**; it is a pre-push discipline. Currently **28/28 clean**. Be honest that this half
   is an honour system — a single-maintainer project can carry that; a hard gate it is not.

*Not done: a self-hosted runner.* GitHub explicitly recommends against self-hosted runners
on **public** repos — a fork PR can execute arbitrary code on the runner, and here the
runner would be the box holding the Cadence licence. Given (1) and (2) already cover the
known bug class, that exposure isn't worth it unless QuickUVM goes private.

*Live landmine (separate PR):* those ~43 benign `<agent>_cfg <agent>_cfg;` declarations
compile only by luck. The day a template edit writes `<agent>_cfg::` inside `<dut>_env_cfg`,
every bench breaks exactly as `_cov` did. Renaming them at the source is the real fix — but
it rewrites every `gen/` tree, so it must be its own blessed one-time regeneration commit,
kept out of R1 so the byte-identity gate stays meaningful.

### Empirical validation — `rvtimer` reproduce-and-compare
[`maturity_assessment_rv_timer.md`](maturity_assessment_rv_timer.md) upgrades the
on-paper [`comparison_opentitan.md`](comparison_opentitan.md) to a **built,
Xcelium-green** `rv_timer`-equivalent bench ([`examples/rvtimer/`](../examples/rvtimer/),
4 tests 0/0/0). Verdict: **generation parity is strong and proven** (~873 lines of DV
generated, ~42 hand-written); the honest gaps are reuse/VIP + closure infra. Net-new
action items it surfaced, beyond R1/V2:
- **CSR-test register exclusions** — a `csr_excl`-equivalent config knob so a
  hardware-set RO register (e.g. an interrupt-status reg) opts out of
  `uvm_reg_access_seq` without a manual `NO_REG_ACCESS_TEST` resource in the RAL.

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
