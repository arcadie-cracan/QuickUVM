# rvtimer — an rv_timer-equivalent block bench (QuickUVM maturity assessment)

An **empirical reproduction** of a mature IP-block DV environment — modelled on
OpenTitan's `rv_timer` — built with QuickUVM to measure how much of a real
register-block verification environment the generator produces, and where a human
must fill functional code. It is the built-and-run companion to the on-paper
[`docs/comparison_opentitan.md`](../../docs/comparison_opentitan.md); the full
scorecard is in [`docs/maturity_assessment_rv_timer.md`](../../docs/maturity_assessment_rv_timer.md).

**Fairness note.** The register bus is held **generic (single-cycle / APB-style)**,
NOT TileLink. TL-UL is OpenTitan-specific and outside QuickUVM's generic-generator
scope; holding it generic isolates the DV-*generation* capability from the bus
protocol. TL-UL enters a real bench only at the adapter's `reg2bus`/`bus2reg`, which
is user code in both worlds.

## The block

A minimal timer (`rtl/rvtimer.sv`): a `mtime` counter increments by `CFG.step`
each cycle when `CTRL.enable`; on reaching `MTIMECMP` it latches `INTR_STATE` and,
if `INTR_ENABLE`, asserts the `intr` output. Registers (16-bit): `CTRL`, `CFG`,
`MTIMECMP`, `INTR_ENABLE` (R/W) + `INTR_STATE` (RO). The external `uvm_reg_block`
(`ral/rvtimer_ral_pkg.sv`) is hand-written — faithful to QuickUVM's design, which
consumes the RAL by name and delegates its *generation* to reggen/SystemRDL.

## What QuickUVM generated vs what was hand-filled

- **Generated (no edits):** both agents (driver/monitor/sequencer/agent/interface),
  the transaction, env + env_cfg, the scoreboard/predictor/comparator seam, the RAL
  wiring (build/lock/adapter/predictor/backdoor), the **C5 CSR test suite**
  (`hw_reset`/`bit_bash`/`rw`), the covergroup (from `coverage_models:`), `tb_top`
  (both interfaces + the DUT + reset generator, auto-wired), the K1 SVA on `intr`,
  and the filelists.
- **Hand-filled (pragma regions + inputs):** the DUT RTL, the external RAL, the
  adapter `reg2bus`/`bus2reg`, the driver read-data sampling, the monitor's
  combinational-read re-sample, the reference-model `predict()` (the golden shadow
  of the register read path), and the directed timer-interrupt check in `rand_test`.

## Run (Xcelium)

From `sim/` (all pass with 0 UVM_WARNING/ERROR/FATAL on Xcelium 25.09):

```
xrun -f xrun.f +UVM_TESTNAME=rand_test                  # data-path scoreboard + directed timer interrupt
xrun -f xrun.f +UVM_TESTNAME=rvtimer_csr_hw_reset_test  # C5 CSR: reset values
xrun -f xrun.f +UVM_TESTNAME=rvtimer_csr_bit_bash_test  # C5 CSR: per-bit R/W
xrun -f xrun.f +UVM_TESTNAME=rvtimer_csr_rw_test        # C5 CSR: front-door vs backdoor
```

`rand_test` drives random register traffic (checked by the golden-model data-path
scoreboard), then arms the timer through the RAL and verifies the interrupt asserts
and clears. The `rw` CSR test needs the backdoor (`register_model.backdoor_root`);
`INTR_STATE` is opted out of it (`NO_REG_ACCESS_TEST`) as a hardware-set RO register.

## Regenerate

```
quick-uvm generate -c examples/rvtimer/rvtimer.yaml -o examples/rvtimer/gen
```

Reproduces `gen/` byte-for-byte (the pragma-region fills are preserved by the
merger; enforced by the byte-identity gate).
