# QuickUVM parity roadmap (v0.3 → v1.0)

Goal: close the testbench-flexibility gap to UVMF / Doulos EasierUVM / icdk uvmgen,
while preserving QuickUVM's identity (simplicity + fail-closed pragma preservation).

See `comparison.md` for the feature comparison and `code_preservation.md` for the
merge contract that every phase below must keep intact.

## The gating fork: output layout

Everything above "config objects" (reuse, hierarchy, parameterized VIP, QVIP) needs the
layered package model (`<agent>_pkg` / `<env>_pkg` / bench) instead of today's monolithic
`tb_pkg.sv`. Plan: make layout a config switch —
- `layout: flat` — today's Cliff-Cummings/Paradigm-Works single-package style (kept).
- `layout: packaged` — new, parity track.

## Known bugs to fix as part of the relevant phases

- **Unwired `active` flag (fix in F1):** `AgentConfig.active` exists but
  `agent_agent.svh.j2` has the `is_active` assignment commented out and nothing sets it,
  so `active: false` has no effect — passive agents stay UVM_ACTIVE.
- **Silently-unconnected non-primary agents (fix in C1):** `env.svh.j2` instantiates all
  agents but wires only `agents[0]` to the scoreboard/coverage; extra agents' analysis
  ports connect to nothing.

## Dependency-ordered phases

```
F1 config objects (+active fix) ─┬─> F2 VIP packaging ─┬─> H1 sub-environments
                                 ├─> C1 analysis fabric (+unconnected-agent fix)
                                 ├─> C2 virtual sequences
                                 ├─> C3 parameterization
                                 └─> C4 register model (RAL)
                                                        └─> A1 QVIP, A2 scoreboard lib
```

### F1 — Configuration objects + uvm_config_db (foundational) — DONE (v0.3.0)
Generates `<agent>_config` (is_active, vif, knobs) and `env_config`; propagates
test → env → agent via `uvm_config_db` (replaced `uvm_resource_db` vif passing);
`is_active` now wired from YAML (the unwired-`active` bug is fixed). New pragma:
`config_var_additional`. Covered by `tests/test_config_objects.py` (80 tests green).
Breaking for existing TBs — the merge carries pragma bodies, but **`spi/quickuvm_tb`
must be regenerated** (vif passing changed from resource_db to config_db).

### F2 — VIP package restructuring (foundational)
`layout: packaged`: standalone `<agent>_pkg`, `<env>_pkg`, thin bench; per-package `.f`.
Accept: `<agent>_pkg` compiles standalone.

### C1 — Declarative analysis fabric (MVP per-agent routing) — DONE (v0.4.0)
Opt-in `analysis:` block: `coverage: [<agent>...]` (one `<agent>_cover` per listed
agent) and `scoreboards: [{name, source}]` (a `tb_scoreboard` bound to `<source>.ap`).
When omitted, the env keeps the legacy single-stream wiring **byte-identical** (verified),
so single-agent TBs (incl. `spi/quickuvm_tb`) need no migration. Fixes the
unconnected-non-primary-agent bug for routed agents. Covered by
`tests/test_analysis_fabric.py` (+ `with_analysis` marker/idempotency variant); 88 green.
Kept single-stream `tb_scoreboard` (one transaction type). Deferred to a later step:
full multi-predictor / `tlm_connections` fabric for "A drives → predictor → scoreboard
← B monitors" topologies (and multi-transaction scoreboards).

### C2 — Virtual sequencer + env/bench sequences
`env_vsqr` (agent sequencer handles), `env_vseq_base`; tests run vseqs.
Accept: a vseq coordinating ≥2 agents.

### C3 — Parameterization
`parameters:` at interface/agent/env/bench; param refs in widths; `#(...)` threaded
via Jinja macros. Accept: one agent reused at two widths.

### C4a — Register model (RAL), front-door — DONE (v0.5.0)
Opt-in `register_model:` block. The uvm_reg_block is generated externally (reggen);
QuickUVM generates: the `<adapter>` (uvm_reg_adapter skeleton — reg2bus/bus2reg are
pragmas, the protocol/paging mapping is user code), env/test wiring (test_base builds +
locks the model into env_config; env does `map.set_sequencer` + an optional
`uvm_reg_predictor` for explicit prediction), the reg-package import, and an optional
`reg_test` (uvm_reg_hw_reset_seq + uvm_reg_bit_bash_seq). Omitting the block is
byte-identical (verified). Covered by `tests/test_register_model.py` (+ `with_regmodel`
marker/idempotency variant); 98 green.

### C4b — Register model, backdoor (hdl_path) — DONE (v0.6.0)
`register_model.backdoor_root` emits `model.add_hdl_path(<root>)` in test_base, and
`reg_test_door: backdoor` makes `reg_test` run via `set_default_door(UVM_BACKDOOR)` —
peek/poke straight to RTL storage, sidestepping SPI paging + pipelined reads. Relies on
reggen emitting per-register `add_hdl_path_slice` (done in `tools/sysbus_reggen.py`).
Front-door default unchanged (byte-identical). Covered by `tests/test_register_model.py`.

### H1 — Sub-environments
`subenvs:`; nest child env packages + configs + param propagation. Depends F1/F2/C1/C3.

### A1 — QVIP / external VIP (optional, low ROI here)
### A2 — Scoreboard library / comparison strategies (in-order / out-of-order / race)

## Cross-cutting (every phase)
- Keep fail-closed merge + rolling backups working; extend marker-regression suite to
  each new config shape (multi-agent, params, subenvs).
- F1/F2 are breaking: provide migration steps; validate against `spi/quickuvm_tb`.
- One worked example + docs per phase.

## Parity tiers / sequencing
| Tier | Phases | Result |
|---|---|---|
| MVP parity (recommended) | F1 + C1 + C4 | config objects, multi-agent checking, RAL |
| Reuse parity | + F2 + C2 | packaged reusable VIP, virtual sequences |
| Full parity | + C3 + H1 + A1/A2 | parameterized, hierarchical, QVIP (UVMF-class) |

Recommendation: pursue MVP parity first; defer F2/H1/QVIP unless a subsystem-level need
forces them. QuickUVM's niche is simplicity + best-in-class code preservation.
