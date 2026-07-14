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

## Next

* **Slice 0b** — `spi_host_reg_generic.sv` (replaces `spi_host_reg_top` + `spi_host_window`),
  then the same smoke test driven through the register bus.
* **Slice 1** — the generated UVM bench, then immediately the mutations. A green bench that has
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
