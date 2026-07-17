# ahb_regs — RAL over a registered-read AHB-Lite bus

**Closes the registered-read RAL gap the campaign found on OpenTitan `spi_host`** (T2 §7): a
pipelined register bus returns read data one cycle *after* the address, and a naive
single-cycle access reads the *previous* register — stale data. This bench reproduces that
break and shows the fix.

## The gap (reproduced)

`rtl/ahb_regs.sv` is an AHB-Lite register slave with a **registered** read: the master drives
`HADDR` in the address phase (cycle N) and `HRDATA` is valid in the data phase (cycle N+1),
and the address is only held for that one address-phase cycle. A driver that samples `HRDATA`
in the *same* cycle it drives `HADDR` reads the previous access's data. Mutate the driver's
capture to single-cycle and every CSR read is off by one register:

```
ctrl    read 0xcafe0000  (status's value)     should be 0x0
cfg     read 0x0         (ctrl's value)        should be 0xff
scratch read 0xff        (cfg's value)         should be 0xdeadbeef
status  read 0xdeadbeef  (scratch's value)     should be 0xcafe0000        -> 4 UVM_ERRORs
```

That is exactly the "CONTROL reads 0x0 not 0x7f" pathology `spi_host` hit.

## The fix — and it refines the T2 conclusion

T2 concluded a registered-read bus "needs a custom `uvm_reg_frontdoor`." Running it shows the
real requirement is **two-phase bus timing**, and for an in-order pipelined bus that lives in
the **driver seam**, not a frontdoor. `gen/ahb_driver.svh`'s `drive_item_additional` does the
AHB two-phase — drive the address phase, end the transfer (`HTRANS=IDLE`), advance into the
data phase, and capture the now-valid `HRDATA` into the transaction:

```systemverilog
// (default drive = the ADDRESS phase: HADDR/HWRITE/HTRANS=NONSEQ/HWDATA)
vif.cb1.HTRANS <= 2'b00;   // IDLE — end the transfer
@vif.cb1;                   // data phase (skew + registered read settle)
tr.HRDATA = vif.cb1.HRDATA; // capture the read data
```

The generic adapter (`reg2bus`/`bus2reg`) then reads `tr.HRDATA` unchanged — **no custom
`uvm_reg_frontdoor` is needed.** The `register_model.frontdoor:` knob remains for buses whose
request and response are genuinely *decoupled* channels (TL-UL's a/d channels), which AHB is
not.

## Result

All three generated CSR tests pass on Xcelium (`make regress` → 10/10 across two seeds):

```
ahb_regs_csr_hw_reset_test   ahb_regs_csr_rw_test   ahb_regs_csr_bit_bash_test
```

The RAL (`ral/ahb_regs_ral_pkg.sv`, hand-written like `regfile`'s) is consumed by name via
`register_model:`; `backdoor_root` gives `csr_rw` its frontdoor↔backdoor peek/poke.

## Run

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=ahb_regs_csr_hw_reset_test   # or _csr_rw_test / _csr_bit_bash_test
# or the seed regression:
cd ../gen && make regress
```
