# ahb_regs — mutation proof

The bench passes only because the driver captures `HRDATA` in the DATA phase (one cycle after
the address phase). Prove the two-phase timing is load-bearing:

## Baseline — two-phase capture — PASS

`make regress` → 10/10 (hw_reset / csr_rw / bit_bash / rand_test / reg_test, both seeds), 0 errors.

## M1 — naive single-cycle capture → stale reads, FAIL

In `gen/ahb_driver.svh`, replace the two-phase `drive_item_additional` body with a same-cycle
capture (drop the `HTRANS<=IDLE; @vif.cb1;` and capture `HRDATA` in the address phase):

```
[RegModel] ctrl    value read from DUT (0xcafe0000) does not match mirrored value (0x0)
[RegModel] cfg     value read from DUT (0x0)        does not match mirrored value (0xff)
[RegModel] scratch value read from DUT (0xff)       does not match mirrored value (0xdeadbeef)
[RegModel] status  value read from DUT (0xdeadbeef)  does not match mirrored value (0xcafe0000)
UVM_ERROR : 4
```

Every register reads the PREVIOUS access's value — the off-by-one-cycle stale read of a
registered bus. This is the exact pathology T2 found on spi_host (`CONTROL reads 0x0 not 0x7f`);
the two-phase capture is what closes it.
