# cdc_fifo — mutation proof

The cross-domain scoreboard passes only because the popped words actually match the pushed
words across the clock crossing. Prove it has teeth.

## Baseline — PASS

`make regress` → 2/2; `+UVM_TESTNAME=rand_test` → 16 Ran / 16 Passed, 0 warnings, 0 errors.

## M1 — corrupt the crossing → the scoreboard catches every word

In `rtl/cdc_fifo.sv`, flip a bit on the read data:

```
assign rdata = mem[rbin[AW-1:0]] ^ 8'h01;   // corrupt
```

```
[ERROR] Expected rdata=76  Actual rdata=77
[ERROR] Expected rdata=a4  Actual rdata=a5
... (every word)
TEST FAILED - 16 Ran / 0 Passed / 16 Failed    UVM_ERROR : 17
```

The scoreboard matches the write-domain stream against the read-domain stream and flags the
mismatch on every crossing — cross-domain data integrity is genuinely checked.

## Note on the two bugs the build itself caught (see README)

- Remove the `wfull` register (make it combinational) → the sim deadlocks in delta cycles
  (the `wxfer → wready → wxfer` loop); the run hangs at ~185 ns of sim time.
- Remove the `sample_dut_additional` re-sample in `wr_monitor` → the source stream lags its
  qualifier by one word (a phantom leading item), and every compare mismatches by one.
