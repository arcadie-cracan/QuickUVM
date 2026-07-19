# dualreg — multi agent-driven resets, mixed polarity (M1)

Two registered lanes on one clock, but each lane's reset is **driven by its own
agent's sequences** (agent-driven, not a top-generated external reset) — and at
**opposite polarities**.

```
dualreg.yaml
  dut: {reset: a_rst_n}          # the default reset PORT
  reset: {active_low: true}      # its polarity (the reset: mapping)
  agents:
    - {name: a, ...}                               # drives a_rst_n (active-low, implicit)
    - {name: b, reset_port: b_rst,
               reset_port_active_low: false, ...}  # drives b_rst (active-high)
```

An agent-driven reset is an agent **input port** that the agent drives: the driver
parks it *asserted* at time 0, the sequences constrain it *inactive* during normal
stimulus, and the monitor re-samples it. Two knobs make this per-agent:

- **`reset_port`** names which of the agent's own input ports is its reset. Omitted
  ⇒ falls back to the port named `dut.reset` (so a single-reset bench like
  [`simple_reg`](../simple_reg/) is byte-identical).
- **`reset_port_active_low`** overrides the global `reset: {active_low}` for that
  agent — here agent `b` is active-high.

QuickUVM emits each agent's reset at its own polarity:

| | agent a (active-low) | agent b (active-high) |
|---|---|---|
| driver park (asserted) | `vif.a_rst_n <= '0;` | `vif.b_rst <= '1;` |
| sequence constraint (inactive) | `tr.a_rst_n=='1;` | `tr.b_rst=='0;` |
| monitor re-sample | `if (!vif.a_rst_n) ...` | `if (vif.b_rst) ...` |
| cover bins | `dorst={'0} norst={'1}` | `dorst={'1} norst={'0}` |

*(This slice also fixed a latent bug — those four sites previously hardcoded the
active-low form, so an active-high reset generated wrong stimulus.)*

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=dualreg_test
```
Both lane scoreboards (`a_sb`, `b_sb`), each reset-aware at its own polarity, pass
**on Xcelium** (0 errors).

## Scope / notes
- Fail-closed: a `reset_port` that isn't the agent's own input port; combined with
  `reset: {external: true}`; or combined with M1 `clock:`/`reset:` lists.
- Deferred: agent-driven resets combined with M1 multi-clock domains.
