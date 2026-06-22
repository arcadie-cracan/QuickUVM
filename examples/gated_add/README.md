# gated_add — per-field `rand_mode` (S1)

A trivial combinational adder `y = a + bias` whose only purpose is to demonstrate
**`rand_mode: false`**: a field declared `rand` but with its randomization **disabled
by default**, so it holds its value until a sequence re-enables it.

## What `rand_mode: false` generates

`bias` is `rand bit [7:0] bias;` (a real rand field), but the transaction's `new()` calls
`bias.rand_mode(0);` — so a plain `tr.randomize()` leaves `bias` unchanged (0). A sequence
re-enables it per item with `tr.bias.rand_mode(1);`. (Only valid on a rand input port;
`rand_mode: false` with `randomize: false`, on an output, or together with a per-field
`constraint`, is rejected at config time. A held field is a fixed state value, so a
transaction-level `constraints:` entry referencing it solves against that held value.)

- **`rand_test`** — the default sequence; `bias` stays 0, so `y == a`. **41/41 on Xcelium**
  (sampled `bias` is 0 on every transaction; the lone `0xff` is the driver's idle/init vector).
- **`bias_on_test`** — runs the `bias_on` directed sequence, whose body calls
  `tr.bias.rand_mode(1)` before randomizing; `bias` then takes the full random range and
  `y == a + bias`. **41/41 on Xcelium**.

Both pass because the reference model adds the **sampled** `a + bias` either way — the
feature being shown is the stimulus control (held vs randomized), not a checker change.

## Layout

- `rtl/gated_add.sv` — combinational `a + bias`.
- `gated_add.yaml` — config; `bias` has `rand_mode: false`, plus a `bias_on` directed seq.
- `gen/` — generated TB; hand-filled pragmas: the reference `y = a + bias` and the
  `bias.rand_mode(1)` re-enable in `bias_on.svh`.
- `sim/xrun.f` — Xcelium filelist.

## Run

```bash
quick-uvm generate -c gated_add.yaml -o gen
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test      # bias held 0,  y == a
         xrun -f xrun.f +UVM_TESTNAME=bias_on_test    # bias random,  y == a+bias
```
