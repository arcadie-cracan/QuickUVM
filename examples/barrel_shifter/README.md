# barrel_shifter — combinational-DUT example

A first **combinational** QuickUVM example: a parameterized barrel shifter
(`SLL/SRL/SRA/ROL/ROR`, `W=32`). Demonstrates `dut.combinational: true` — the TB
clock is a pure cadence (one vector/cycle), not wired to the DUT, and the monitor
samples inputs+outputs together race-free via a monitor clocking block.

## Layout
- `rtl/barrel_shifter.sv` — the clean MIT combinational DUT.
- `barrel_shifter.yaml` — the QuickUVM config (`combinational: true`).
- `gen/` — the generated testbench. Only two pragma sections are hand-filled:
  - `sb_calc_exp.svh` `prediction_logic` — the golden model (`out = shift(in, amt, op)`).
  - `bs_sequence.svh` `do_item_constraints` — `op inside {[0:4]}`.
- `sim/xrun.f` — Xcelium filelist (wires the **real** `rtl/` DUT, not the generated stub).

## Sequence library (S2)
`barrel_shifter.yaml` also declares an `agents[].sequences` library: `bs_rand`
(a longer random soak) and `bs_amt_walk` (an `incrementing` sweep that walks the
shift amount `amt = 0..31` while data/op stay random). The `amt_sweep` test
**selects** `bs_amt_walk` (`tests[].sequence: {agent: bs, name: bs_amt_walk}`)
instead of the default `bs_sequence`.

## Generate + run
```bash
quick-uvm generate -c barrel_shifter.yaml -o gen     # regenerate (preserves pragmas)
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test     # -> TEST PASSED, 501/501
cd sim && xrun -f xrun.f +UVM_TESTNAME=amt_sweep     # -> TEST PASSED, 33/33 (amt 0..31)
```

## Notes
- The generated `gen/barrel_shifter.sv` is an `always_comb` **stub**; `sim/xrun.f`
  compiles the real `rtl/barrel_shifter.sv` instead.
- The cadence `clock.period` must exceed the DUT's combinational settling time.
