# priority_encoder — combinational example (multi-output)

A second combinational QuickUVM example: a parameterized priority encoder
(`N=8`). `idx` = index of the highest set bit of `req` (MSB priority);
`valid` = `|req`. Exercises `dut.combinational: true` on a **multi-output** shape
(both `idx` and `valid` are checked) — no QuickUVM core changes vs the barrel
shifter; the flag drops straight in.

## Layout
- `rtl/priority_encoder.sv` — clean MIT combinational DUT.
- `priority_encoder.yaml` — config (`combinational: true`).
- `gen/` — generated TB; two hand-filled pragmas:
  - `priority_encoder_reference_model.svh` `prediction_logic` — golden `predict()` model (highest-set-bit + `|req`).
  - `pe_seq.svh` `do_item_constraints` — a `dist` biasing `req` toward `0x00`
    (the `valid=0` corner) and `0xFF`.
- `sim/xrun.f` — Xcelium filelist (real `rtl/` DUT, not the stub).

## Run
```bash
quick-uvm generate -c priority_encoder.yaml -o gen
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test     # -> TEST PASSED, 501/501
```
