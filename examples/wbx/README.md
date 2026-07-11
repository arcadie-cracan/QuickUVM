# wbx — K2 whitebox probe example

The interesting state of this DUT is **internal and invisible at its ports**: a FIFO
`fill_level`, an FSM `state` (enum), and a `real` accumulator `acc`. `wbx.yaml`
declares `probes:` that tap them by hierarchical path — **observe-only** (a continuous
`assign` into a generated probe interface; never driven) — so the testbench can
assert and cover internal behaviour without exposing debug ports.

## What the probes do

```yaml
probes:
  - {name: fifo_lvl,  path: fill_level, width: 3, coverage: true}   # numeric bins
  - {name: fsm_state, path: state, enum: {IDLE: 0, BUSY: 1, FULL: 2}, width: 2, coverage: true}  # SYMBOLIC bins
  - {name: acc,       path: acc, real: true}                        # SVA-checkable, no covergroup
```

- **`wbx_probe_if.sv`** carries the raw taps + a `mon_cb` clocking block + a
  `probe_sva` pragma (filled here with the internal invariants: `fifo_lvl <= 4`,
  `state==FULL ⇒ fifo_lvl==4`, `state==IDLE ⇒ fifo_lvl==0`, `acc >= 0.0`).
- **`tb_top.sv`** instantiates the probe interface and emits `assign
  probe_if.<name> = dut_inst.<path>;` (the XMR), then publishes the vif via
  `uvm_config_db`.
- **`wbx_probe_monitor.svh`** samples the taps and covers them — the FSM coverpoint is
  **symbolic** (it `$cast`s the raw bits to the enum, so bins are `IDLE`/`BUSY`/`FULL`).

## Run (Xcelium)

```
xrun -f xrun.f +UVM_TESTNAME=rand_test     # 0 UVM_WARNING/ERROR/FATAL
```

Random push/pop stimulus walks the FIFO through all three FSM states; the probe SVA
holds and the coverage is collected.

## Mutation proof

The probe SVA genuinely checks the *internal* encoding. Break the FSM so it declares
`FULL` one slot early:

```
else if (fill_level >= DEPTH - 1) state = FULL;   // BUG
```

and re-run: `a_full_max` (`state==FULL ⇒ fifo_lvl==4`) **fires** and the sim fails —
a wrong internal encoding, invisible at the ports, is caught by the whitebox probe.

## Notes

- Observe-only: the probe fields are interface INPUTS fed by continuous `assign`s;
  the generator never emits `force`/`deposit` (driving internals is out of scope).
- `real` probes are SVA-checkable but carry no `coverage` (SystemVerilog forbids a
  covergroup coverpoint on a `real`).
- Paths are relative to the DUT instance; the mechanism (XMR) fails **closed** — a
  wrong/renamed path is an elaboration error, not a silent miss.
