# Changelog

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
