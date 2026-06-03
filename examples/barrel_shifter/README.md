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

## Generate + run
```bash
quick-uvm generate -c barrel_shifter.yaml -o gen     # regenerate (preserves pragmas)
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test     # -> TEST PASSED, 501/501
```

## Notes
- The generated `gen/barrel_shifter.sv` is an `always_comb` **stub**; `sim/xrun.f`
  compiles the real `rtl/barrel_shifter.sv` instead.
- The cadence `clock.period` must exceed the DUT's combinational settling time.
