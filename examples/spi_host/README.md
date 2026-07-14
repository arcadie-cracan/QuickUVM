# spi_host — OpenTitan's real SPI controller (campaign target T2)

The DUT is **OpenTitan's `spi_host`**, vendored unmodified. Not RTL I wrote.

That distinction is the entire point. Three QuickUVM features — `clock[].source: dut`,
`respond: prefetch`, and per-lane `inouts` — were built and mutation-proved against
`examples/spi_device/`, whose SPI host **I wrote myself**. So I also chose its timing. A feature
that only works against RTL its own author designed has proved nothing.

## Status

**Slice 0a — done.** One full-duplex SPI byte, both directions, through OpenTitan's
`spi_host_core`. Plain SystemVerilog, no UVM, no register block, no wrapper: `sim/tb_core_smoke.sv`.

    xrun -sv -f sim/core_smoke.f -top tb_core_smoke

    PASS  sck toggled (8 rising edges)
    PASS  sck period == 2*(CLKDIV+1) core clocks
    PASS  the device saw 8 sck edges
    PASS  the device received the host's byte: got a5, expect a5
    PASS  the host received the device's byte: got 3c, expect 3c
    PASS  no stall

**Mutation-proved (M6):** invert the RX bit inside the *vendored* `spi_host_shift_register.sv`
and the smoke test fails (`got c3, expect 3c`). The vendored RTL really is under test, and the
smoke test really can fail.

This slice exists because T1's lesson was *validate the DUT before you build the bench* — there,
a directed RTL smoke test caught a real bug (a byte-enable sum overflowing to zero) that the
bench would have hidden. It is split from Slice 0b deliberately, so that "do we understand this
DUT?" is answered with **zero wrapper risk**.

## What the DUT already told us

`spi_host_core`'s SPI port is:

    output logic [3:0]  sd_o;
    output logic [3:0]  sd_en_o;    // a PER-LANE output enable
    input        [3:0]  sd_i;

**OpenTitan's taped-out silicon has exactly the per-lane output enable QuickUVM gained in the
responder-timing slice.** A scalar enable cannot connect to this port at all. That fix was made
from first principles against a DUT I wrote; here is the independent confirmation.

**Slice 0b — done.** The same byte, driven through the **register bus** on a real tri-state pad
ring: `rtl/spi_host_reg_generic.sv` (ours, replacing `spi_host_reg_top` + `spi_host_window`),
`rtl/spi_host_ot.sv` (ours, the top + pad ring), `sim/tb_reg_smoke.sv`.

    xrun -sv -f sim/reg_smoke.f -top tb_reg_smoke      # *** SLICE 0b PASSED ***

**Both traps mutation-proved.** The register block has two ways to produce a bench that passes
by doing nothing, and this smoke test falls into both:

| mutation | result |
|---|---|
| the sequence forgets `CONTROL.OUTPUT_EN` | **FAILED** — `sck` never toggles; the host reads back **`0xff`** |
| `COMMAND` driven from a *value* instead of the **write strobe** | **FAILED** — no command ever issues |

Look at the first one's signature: **`0xff` is the pull-up value.** `OUTPUT_EN` resets to 0 and
gates sck, csb and every sd lane, so the DUT drives *nothing* — and the bus floats high. No X, no
error, no protocol violation. It looks perfectly quiet and legal. A check that only asked "is
there an X on the bus?", or any scoreboard predicting from the observed value, would pass while
testing nothing.

`COMMAND` is `hwext`+`hwqe` upstream — it has **no storage**, and the command launches on the
*write strobe* (`command_valid = |cmd_qes`). Drive it from a value and the DUT sits idle forever.

**Slice 1 — done. The generated UVM bench, on OpenTitan's real RTL.**

Two agents: a register-bus initiator on the core clock, and the SPI device as a **`prefetch`
responder on the DUT-driven `sck`**, driving **nothing but tri-state lanes**.

    make -C gen regress          # rand_test -> 2674/2674, 0 UVM_ERROR

### THE MUTATION THIS TARGET EXISTS FOR (M3)

`respond: prefetch` -> `on_request`, against **taped-out silicon**:

    TEST FAILED — 8/8 RXDATA vectors fail, 10 UVM_ERROR, [DEAD_RESPONDER]

**`prefetch` is load-bearing on real hardware.** `on_request` waits for the monitor to publish
a request — which happens at *frame end* — so the device never drives during the frame at all.
The full-duplex argument was **not** an artefact of RTL I wrote myself.

### The other mutations

| mutation | result |
|---|---|
| the device sends a different byte | **8/8 RXDATA vectors FAIL** — the check is real, not an echo |
| the device never drives (releases the bus) | **8/8 FAIL** — the pull-ups do not fake a device |

### What the liveness check caught

The first run of this bench reported **`TEST PASSED — 2622 Ran / 2622 Passed`** *with one
`UVM_ERROR`: `NO_RXDATA`*. Those 2,622 "passes" were **idle bus beats echoing themselves** —
the predictor had never seen a single read come back. Without the end-of-test liveness check
this would have been a clean green bench measuring **nothing**.

The cause was a genuinely subtle SystemVerilog trap, now documented in `gen/regbus_driver.svh`:
**a clocking-block drive issued the instant `@vif.cb1` returns lands on the SAME clocking event
as the drive before it.** So the driver's `req <= 1'b0` deassert silently *overwrote* its own
`req <= tr.req`, and the request pulse never reached the wire. `addr` and `wdata` changed
(nothing deasserted them) so the bus *looked* busy — but `req` stayed low, the DUT saw no
access, and every register beat vanished. The wire probe settled it: `req` was high on 11 clock
edges while the driver had driven 26 items.

## Next

* **Slice 2** — the generated UVM bench, then immediately the mutations. A green bench that has
  not been mutation-proved does not count.
* **The mutation that justifies T2 (M3)** — flip `respond: prefetch` → `on_request` against
  *this* RTL. If it stays green, the full-duplex argument was an artefact of my own DUT, and that
  is a headline finding. **Report either way.**

## What is vendor, what is ours

* **Vendor, unmodified** (lowRISC/opentitan, Apache-2.0): every line of the SPI protocol — see
  `rtl/vendor/README.md`. `grep -rl tlul rtl/vendor/` returns nothing.
* **Ours** (the declared bus normalisation): `spi_host_reg_generic.sv` and `spi_host_ot.sv`,
  replacing the three TL-UL files.

**The fairness argument, stated up front:** `spi_host` is an SPI *controller*. The bus under test
is **SPI, not TL-UL** — TL-UL is only how firmware configures it. Removing it deletes the
configuration path and nothing else. The protocol, the tri-state lanes, CPOL/CPHA, the segment
engine and the device agent are all still here.
