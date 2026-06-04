# sat_adder — DPI-C reference-model example (K0)

A combinational unsigned **saturating adder** (`W=8`): `sum = min(a+b, 0xFF)`, `ovf` on
overflow. It's the worked example for **K0** — the golden model is written in **C** and
called per transaction via **DPI-C**, instead of in SystemVerilog.

## What `reference_model.language: c` generates
- `sat_adder_reference_model.svh` — a **fully-generated SV bridge** (do not edit): an
  `import "DPI-C" function void sat_adder_predict(input byte a, input byte b, output byte
  sum, output byte ovf);` plus `sat_adder_predictor::predict()`, which copies the sampled
  transaction, calls the C function, and unpacks the expected `sum`/`ovf`.
- `sat_adder_reference_model.c` — **the only file you edit**: the golden model in C
  (inputs by value, expected outputs by pointer), with the logic in the
  `reference_model` pragma region.

The scoreboard (`sat_adder_scoreboard`/`_predictor`/`_comparator`) is unchanged — K0 just
swaps the `predict()` *body's* language. Field→type mapping is by width
(≤8→`byte`/`char`, ≤16→`shortint`/`short`, ≤32→`int`/`int`, ≤64→`longint`/`long long`).

## Layout
- `rtl/sat_adder.sv` — clean MIT combinational DUT.
- `sat_adder.yaml` — config (`combinational: true`, `reference_model.language: c`).
- `gen/` — generated TB; the only hand-filled pragma is the C golden model in
  `sat_adder_reference_model.c`.
- `sim/xrun.f` — Xcelium filelist; lists the **`.c`** so xrun compiles + links the DPI model.

## Run
```bash
quick-uvm generate -c sat_adder.yaml -o gen
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test    # -> TEST PASSED, 201/201 (golden model in C)
```
