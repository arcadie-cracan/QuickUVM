# Changelog

## Unreleased

A reset nobody drives. **Changes generated output** for configs in one shape —
which did not elaborate before; every committed example regenerates
byte-identically (none is in that shape).

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
