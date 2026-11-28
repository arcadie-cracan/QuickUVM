# Changelog

## Unreleased

### `resolve` follows the bench's shape (#121)

**Changes the output of `quick-uvm resolve`** on three bench shapes. Generated
testbenches change in TWO cases, both in the env and both marked below ("The
guard", "The env's advice"); every committed example regenerates
byte-identically.

`resolve` mirrors the templates, and nothing compared the two. It applied the
plain bench's rules everywhere, so on an agent with `replicas` / `instances`, on
`kind: vip` and on a composition (`subenvs`, with or without a boundary agent)
the answer to "what will I get" was wrong in several ways at once.

- **The implicit pair.** Without an `analysis:` key `resolve` reported scoreboard
  `sbd` and a coverage collector on the first agent, `origin: inferred`,
  whenever there was an agent. The env renders that pair only on a plain bench
  (and a `selftest`). On the three shapes neither component is generated, and a
  consumer that wrote the reported entries back into the config — the natural
  way to keep them — got a config that is refused: the collector on `replicas`,
  any analysis next to `instances`, both entries on a VIP and on a composition.
  `resolve` now reports the pair only where it is rendered
  (`ProjectConfig.implicit_analysis_wired`); `analysis.mode` is still `implicit`
  there — the key is absent, nothing is inferred for it.
- **New: `instances`.** A bench with `replicas` / `instances` DOES hold
  components nobody declared — one scoreboard per instance. They are reported
  under a new top-level key, present only on such a bench:
  `instances: [{name, agent, origin, scoreboard: {name, origin, owner}}]`. The
  instance's `origin` is `inferred` for a replica (its name is derived) and
  `declared` for an `instances` entry; the scoreboard's is always `inferred`;
  `owner` is the element that owns its files in `manifest`
  (`scoreboard:<instance>`). Kept out of `analysis` on purpose: they cannot be
  declared there, and `analysis` stays "what the YAML could say".
- **New: `wired: false`.** Marks an entry that is in the YAML, is accepted, and
  is rendered as no component — it was reported like any declared entry. Three
  places: a scoreboard declared on a `replicas` bench (the env holds only the
  per-instance ones; on the default flat layout the bench is byte-identical with
  the entry, without it, or with it renamed), a virtual sequence declared on a
  composition (only `<top>_vseq` is generated), and a coverage entry on a VIP
  (its covergroup ships in the agent package; there is no env to hold a
  collector). The key appears only on such entries.
- **A composition's guards and virtual sequence.** A subsystem top always
  generates `<top>_vseq`, which drives every active boundary agent, and its env
  raises `UNCHECKED_AGENT` for each one no scoreboard names. `resolve` applied
  the flat rules instead (a virtual sequence from two stimulus agents up, the
  primary agent excused) and so reported no virtual sequence and, for a top with
  one boundary agent, no guard — for a bench that warns at every run. It now
  reports both; the rule lives in one place
  (`ProjectConfig.unchecked_boundary_agents`), read by the template and the
  report.
- **A VIP.** `kind: vip` emits agent packages and a manifest. `resolve` reported
  the default `test1`, an auto virtual sequence and `UNCHECKED_AGENT` guards for
  it; `tests`, `virtual_sequences` and `guards` are now empty there. The agents'
  sequences are still listed — they ship in the packages.
- **Scope, stated.** On a composition `resolve` describes the top level only:
  each block's env, guards and virtual sequences are its own config's answer.
  Still not reported, on any shape: the tests a `register_model` generates
  (`<dut>_reg_test` and one per `csr_tests` kind).
- **The guard (changes generated output).** `UNCOVERED_AGENT` — "declaring this
  scoreboard cost you the implicit collector" — also fired on a `replicas` bench
  that declared a scoreboard without a `coverage` key, where there never was a
  collector and none can be asked for. It is no longer rendered or reported
  there. `alert_array` and `nchan` carry `coverage: []` from when it was needed
  to quiet that warning; it is harmless and no longer required.
- **The env's advice (changes generated output).** The `UNCHECKED_AGENT` comment
  in a composition's env told the user to add a `subenv_scoreboards:` entry, a
  key that is rejected; it now names `analysis.scoreboards`. A comment only, in
  the env of a composition with an unchecked boundary agent.
- **Locked against the output.** Each shape has a test that compares the report
  with what the generator writes. Scoreboards and collectors are compared in
  both directions (everything the env declares is reported, and the reverse),
  on generated fixtures and on every committed example; tests and virtual
  sequences in one (what is reported is shipped).

## 1.2.0 — 2026-11-21

Everything merged since 1.1.0: a reset nobody drives is now driven by the
testbench top, `quick-uvm resolve`, opt-in multi-vendor simulation filelists
(`sim:`), a runtime guard for coverage dropped by declaring `analysis:`, and two
portability fixes. The schema additions are opt-in (`sim:`); no key was removed
or changed its meaning. Two changes alter generated output — the monitor startup
(every bench; the committed examples were regenerated with it) and the reset
inference (configs in one shape, described below).

### A reset nobody drives

**Changes generated output** for configs in one shape — which did not elaborate
before; every committed example regenerates byte-identically (none is in that
shape).

- **The shape.** A single-reset bench wires `dut.reset` one of two ways: the top
  generates it (`reset: {external: true}`) or an agent drives it (the port is one
  of that agent's ports). With NEITHER — and `dut.reset` defaults to `rst_n`,
  `external` to false, so a config that said nothing about the reset was in it —
  the config validated, `generate` exited 0, and `tb_top` connected the DUT to
  `<first agent>_if_inst.<reset>`, a signal that interface does not have. Xcelium
  rejects it at elaboration (`*E,CUVUNF`). In a composition the same leaf config
  failed more quietly: the subsystem top gave the leaf's DUT no reset connection
  at all.
- **Inference.** An UNSET `reset.external` now resolves to the top-driven reset
  when no agent declares the reset port (`_infer_reset_driver`): there is exactly
  one way left to drive it. The same rule applies to every `kind`, so a `vip` and
  the bench or `selftest` around it agree on whether the interfaces take the
  reset. `quick-uvm resolve` gained a `reset` entry — `{name, driver: top |
  agent:<name>, origin: declared | inferred}`. Never inferred for a combinational
  DUT, a reset domain list, a subsystem top, or next to a `reset_port`.
  **If you regenerate a bench in this shape:** its interfaces gain a reset input
  and its drivers/monitors wait for the reset; regenerate a VIP together with the
  benches that consume it by reference.
- **A wall for the contradiction.** An explicit `external: false` with no agent
  declaring the port, or an agent `reset_port` next to a `dut.reset` that names a
  different, undeclared port, is a validation error that names the ways out.
- **`kind: selftest` with a top-driven reset** now generates the reset in the
  self-test top and passes it to the interfaces. It used to instantiate them with
  the clock only: the reset was an unconnected input the drivers waited on
  forever (exit 0, a self-test that hangs at time 0).
- **Static gate.** `svcheck.find_dangling_dut_connections` checks, on the
  generated (merged) top, that every signal the `dut_connections` pragma uses is
  declared — in the top or in the interface it is taken from. It runs over every
  example in `tests/test_undriven_reset.py`, next to the type-shadowing gate: the
  check that stands in for a simulator on hosted CI.

### `quick-uvm resolve` — the effective topology, with provenance

- **`quick-uvm resolve -c <yaml> [-o file]`** (and the pure
  `ProjectConfig.resolved()`) prints what a config MEANS, including the
  components the generator supplies without the YAML naming them: the implicit
  scoreboard and coverage collector on the primary agent, the auto virtual
  sequence, the default `test1`, each agent's `<agent>_seq`. Every entry carries
  `origin: declared | inferred`; `guards` lists the runtime warnings the config
  arms (`UNCOVERED_AGENT`, `UNCHECKED_AGENT`). Read-only: it writes nothing.
  `manifest` cannot answer this — it maps files to owners and is byte-identical
  either side of the implicit/declared switch.
- Known limit: a hand-written `tests: [{name: test1}]` is indistinguishable from
  the default and is reported as `inferred`.

### Checking

- **`UNCOVERED_AGENT` warning.** `analysis:` is presence-switched: omit it and the
  env wires a scoreboard AND a coverage collector to the primary agent; declare it
  and only what is listed is wired. Declaring a first scoreboard therefore removed
  a collector that was already there, with no signal anywhere. The env now emits a
  `uvm_warning` naming the primary agent when that happens
  (`ProjectConfig.uncovered_agents`). `coverage: []` written explicitly means
  "measure nothing" and stays silent. No generated output changes for the
  committed examples (`alert_array` and `nchan` now say `coverage: []`, which is
  what they meant).

### Simulation filelists (opt-in `sim:`)

- **Portable `compile.f` + one run script per vendor.** A `sim:` block generates a
  tool-neutral `compile.f` (TB sources, the real DUT RTL via `rtl_filelist`,
  include dirs — no tool switches; a language server reads the same file) and a
  thin `sim_<tool>.sh` per entry of `tools: [xcelium, vcs, questa]` that adds only
  that vendor's UVM / timescale / access switches. Absent ⇒ byte-identical.
  Validated on `examples/reqrsp` with Xcelium, Questa and VCS (0 UVM_ERROR,
  30/30). The RTL is referenced with plain `-f` and run-dir-relative paths: `-F`
  is not portable across the three. See `docs/filelist_generation_analysis.md`.
- **`sim.bender: true`** additionally emits a `Bender.yml`, making the bench a
  Bender package (`bender script vsim | vcs | verilator | flist-plus …`). The
  referenced RTL filelist is inlined (nested `-f`/`-F` are not expanded). Flat
  layout only; `packaged` is refused with an error.

### Fixes

- **Monitor startup is portable. Changes generated output** (every monitor; all
  committed examples regenerated). The single-stream monitor primes one clock
  before its first pairing, so a simulator that schedules the driver's first drive
  after the monitor's first sample (Questa, VCS) no longer pairs the reset output
  with the first stimulus — four examples reported exactly one spurious mismatch
  there, which Xcelium's scheduling masked. Responder / request-fifo monitors are
  exempt.
- **Filelists use POSIX separators.** On Windows the referenced-VIP line came out
  as `-F ..\..\f2_iovip\gen\io_pkg.f`: the byte-identity gate failed on any
  Windows regeneration, and xrun/qrun/vcs read the backslash as an escape, so the
  chained VIP package did not resolve.

### Examples and repository

- **`examples/yapp`** — a packet router (1→3 demux by a 2-bit address, one cycle
  of latency, address 3 drops) checked by a single agent that drives the input and
  observes all three outputs. Green on Xcelium and Questa; the backing bench of
  the QuickUVM Architect walkthrough.
- `.gitattributes` normalises line endings to LF, so a Windows checkout no longer
  drifts from the committed `gen/` trees.

## 1.1.0 — 2026-07-22

Generation manifest + per-item incremental regeneration. Additive and
backward-compatible; the schema is unchanged (every committed example regenerates
byte-identically).

- **`quick-uvm manifest -c <yaml> [-o <dir>]`** — a JSON map of config **element →
  generated files**, grouped by owner (`agent:<name>`, `scoreboard:<name>`,
  `test:<name>`, `vseq:<name>`, `register_model`, `probes`, `vip`) plus an
  `aggregate` group (the whole-config files — packages, filelists, top, env,
  clkgen, DUT stub, Makefile — that must be co-regenerated on any structural
  add/remove/rename). With `-o`, each file carries an on-disk `exists` flag. The
  owner is captured where the element is known, so it is correct even where the
  filename drops the element's name (a flat scoreboard `sbd` →
  `<dut>_scoreboard.svh`). Powers per-item incremental regen and downstream
  tooling (QuickUVM Architect's "not generated" decorations).
- **`generate --only` is now repeatable** — pass `--only <file>` once per file to
  regenerate exactly one element (e.g. all of an agent's files) in a single
  invocation; a single `--only` still works. Pragma preservation and backups are
  unchanged under scoping. An `--only` value that matches no generated file now
  warns instead of silently regenerating nothing.
- Internal: `FileSpec` gained an `owner` field (the two above read it); it does not
  affect rendering.

## 1.0.0 — 2026-07-20

First stable release. QuickUVM is a Python/Jinja2 UVM testbench generator in the
Paradigm Works `uvmtb_template` style: a YAML config in, a complete, runnable,
Xcelium-proven UVM bench out — with user code preserved across regenerations in
pragma-delimited regions, and a schema that refuses to mean nothing (unknown
keys, contradictory knobs, and silently-inert settings are validation errors,
not surprises).

### Why 1.0 now

- **The v0.9 → v1.0 parity roadmap is complete** (`docs/parity_roadmap.md`):
  every tier — composition, multi-clock, reactive agents, VIP reuse, regression
  infrastructure, register coverage — has shipped with a committed, simulating
  example.
- **The schema philosophy audit** (`docs/schema_philosophy_audit.md`) confirmed
  the founding claim — *simple by default, powerful when needed* — 18 findings
  confirmed, 0 refuted, and its entire hardening plan has landed (fail-closed at
  the key layer, the value layer, and the render layer).
- **A six-target reproduce campaign** (`docs/reproduce_campaign_results.md`)
  measured QuickUVM against real industrial benches — OpenTitan (`rv_timer`,
  `spi_host`, alert_handler, entropy_src), UVMF/Caliptra SHA-512 accelerator,
  PULP AXI, lowRISC Ibex — converting each predicted failure into either a
  shipped feature or a documented, honest boundary.
- **Every committed example is CI-gated to regenerate byte-identically** and the
  corpus is Xcelium-green; features ship only after a mutation proof (a test
  that cannot fail proves nothing — so each checker is shown to fire).

### The capability surface

**Core generation.** ~13-line YAML → a complete bench (interface, seq_item,
driver/monitor/sequencer/agent, env, scoreboard split into
predictor/comparator/reference-model seams, base+concrete tests, tb_top,
clkgen, filelists). Flat or `packaged` layout; `kind: bench | vip | selftest`.

**Agents.** Initiator and reactive **responder** agents (`respond: on_request |
prefetch | combinational | pipelined` with per-ID `reorder_by:` out-of-order
responses), **hybrid** responders (`proactive: true`), replica arrays
(`replicas: N` onto one vectored DUT), parameterized multi-instance agents
(`instances:`), bidirectional/open-drain ports (`inouts`, mandatory pullup),
rich port types (enums with symbolic coverage, structs, packed dims, user
types), per-agent clock/reset domains, sequence libraries, field_macros or
manual item style.

**Checking & observability.** `analysis:` is the single checking section:
scoreboards (single- or two-stream, `in_order`/`out_of_order`, `match_key`,
`max_latency` windows in both modes, windowed N:1 statistics via `window:`,
per-scoreboard reference model incl. `language: c` DPI), functional coverage
(bare routing entries or rich covergroup definitions), whitebox probes
(verbatim-XMR `probes:` with enum/struct/real types and probe coverage), and
RAL-driven per-register coverage (`register_model.coverage: true`).

**Registers.** External RAL wiring (`register_model:`), generic adapter +
predictor, frontdoor/backdoor, custom frontdoors, and the C5 CSR suite
(`hw_reset`, `bit_bash`, `rw`, `mem_walk`, `shared`).

**Composition & reuse.** Subsystem benches from reusable block envs
(`subenvs`, ≥2, nested, shared-config auto-namespacing, integer param
propagation), physical inter-block `connections` with fail-closed
width/driver/passivity rules, cross-block scoreboards, **boundary agents**
(top-level agents alongside subenvs), standalone versioned **VIPs**
(`kind: vip` + `.qvip` manifest) consumed by reference (`from_vip:`), and
DUT-less VIP self-tests (`kind: selftest`).

**Clocks & resets.** Multi-clock (`clock:` list, per-domain clkgens, one
resolved timescale), DUT-sourced clocks (`source: dut`), multi-reset domains,
external reset generators — `clock:` and `reset:` are symmetric unions; port
names live on `dut`.

**Regression.** Opt-in `regress:` → a generated Makefile (elaborate-once
tests×seeds matrix, coverage merge) with a severity-based verdict (xrun exits 0
on UVM_ERROR; the Makefile does not).

**Guard rails.** ~245 fail-closed validators with *teaching errors* (a renamed
or moved key tells you its new spelling); generated **runtime** guards where a
wall cannot see the problem: `UNFILLED_PREDICTOR`, `UNCHECKED_AGENT`, dead-
responder and stranded-request liveness, `SB_LATENCY`/`SB_LEFTOVER`. Pragma
preservation is fail-closed too (`--allow-drop` to discard orphaned regions,
`.bak` backups by default).

**Waivers (new in this release).** `dut.unverified_ports:` — a first-class
port-coverage waiver for scan/test/debug pins, validated against the schema's
own knowledge (an agent-connected port cannot be waived) and rendered into the
generated bench; RTL-aware tooling (QuickUVM Architect) consumes it.

### Schema stability

1.0.0 freezes the grammar documented in the README schema block. From here,
renames and moves ship with teaching errors (the old spelling errors out
naming the new one), and behavior-affecting changes bump the minor version.
Downstream tooling can gate on `quick-uvm --version`.

### Upgrading from 0.9.x

The 0.9.x → 1.0 grammar consolidation renamed or moved these keys — each old
spelling now produces a validation error stating the replacement:
`trans_style` → `seq_item_style` · `transaction` → `sequence_item` ·
`count` → `replicas` · top-level `resets:`/`dut.external_reset`/
`dut.reset_active_low` → the `reset:` union · `clocks:` → `clock:` list ·
`agent_refs` → `agents:` entries with `from_vip` · `coverage_models` → rich
`analysis.coverage` entries · top-level `reference_model` → per-scoreboard ·
`subenv_scoreboards` → `analysis.scoreboards` with dotted endpoints. Unknown
keys (including `x_`-prefixed ones) are rejected everywhere.
