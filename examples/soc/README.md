# soc — a subsystem env composing two block envs (H1)

The C-tier **H1** example: a subsystem (top) bench that **composes two block
environments** rather than defining its own agents. Each block is a normal,
standalone QuickUVM bench, reused here as a sub-environment.

## `subenvs:`
```yaml
# soc.yaml
layout: packaged
subenvs:
  - {name: adder,    config: adder/adder.yaml}
  - {name: inverter, config: inverter/inverter.yaml}
tests:
  - {name: soc_test}
```
Each `config` path is resolved relative to `soc.yaml`. `adder/adder.yaml` and
`inverter/inverter.yaml` are ordinary block benches (each with its own agent,
DUT and scoreboard) — you can generate and run either on its own.

## What is generated
QuickUVM generates, in one output directory:

- **Each block's reusable env layer** — the agent VIP package (`a_pkg` / `b_pkg`)
  and the block env package (`adder_env_pkg` / `inverter_env_pkg`), containing the
  block env, its config, and its scoreboard. No block test / tb_top / clock is
  emitted (the top provides those).
- **The top layer**:
  - `soc_env` — instantiates `adder_env` + `inverter_env` and a top virtual sequencer;
  - `soc_virtual_sequencer` — holds a handle to each block's agent sequencer
    (`adder_a_sqr`, `inverter_b_sqr`);
  - `soc_vseq` — fires each block's default sequence, concurrently (`fork … join`);
  - `soc_env_cfg` / `soc_base_test` — the top config aggregates each block's env
    config; the base test populates each (agent cfgs + virtual interfaces) and hands
    it down through the config DB so the composed tree self-configures;
  - `tb_top` — instantiates each block's interfaces + **real DUT**, and publishes
    each block's virtual interface.

Each block keeps **its own scoreboard** checking **its own DUT** (adder: `dout=din+1`,
inverter: `dout=~din`).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=soc_test
```
Both blocks pass **31/31 on Xcelium** (0 errors) — two independently-authored block
envs, composed and driven together in one subsystem bench.

## Notes / scope of this slice
- Composed blocks share one output dir + package namespace, so their block names,
  agent names, interfaces and transaction types must be **unique** across blocks
  (QuickUVM checks this).
- A subsystem does **not** emit per-block DUT stubs — it instantiates each block's
  real RTL (see `sim/xrun.f`).
- Opt-in: a bench with no `subenvs` is byte-identical to before.
- Not yet in this slice: parameter propagation from top to blocks, nested subenvs,
  and cross-block scoreboards.
