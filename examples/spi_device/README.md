# spi_device — a full-duplex SPI device, as a reactive agent

The DUT is an SPI **host**. It generates `sck`, opens frames, and shifts a byte out on MOSI
while shifting one in on MISO. The **testbench is the device** that answers.

Two QuickUVM features exist because of this bench, and it is the bench that can make each
of them fail.

## `clock[].source: dut` — a clock the TB observes but never drives

`sck` is a DUT **output**. Every QuickUVM clock used to come from a generated `clkgen`, so
there was no way to say so — and a `clkgen` on that net fights the DUT's driver:

    xmelab: *E,MULDRN: Variable 'tb_top.sck' has multiple conflicting drivers

The tempting fix is to delete `.sck(sck)` from the `dut_connections` pragma. That
**elaborates clean** — and keys the entire bench to a TB-invented **phantom clock** with no
relation to the DUT's real, divided one. It runs. It passes. It measures nothing. And
regeneration puts the `clkgen` back every time.

So the generator now **refuses** to emit a `tb_top` whose clock the DUT is not connected to,
and the message names the fix rather than just the fault. Try it: delete the connection and
run `quick-uvm generate`.

## `respond: prefetch` — the response cannot depend on the request it accompanies

Full duplex means the host samples MISO on the **very edge** that drives MOSI. So the
device's MISO bit *k* cannot be a function of MOSI bit *k* — **it must already be on the
wire**. Bit 7 has to be presented while CSB is still falling: there is no earlier edge to
hang it on.

The default `on_request` contract cannot do this. It waits for the request, *then* fetches
an item — structurally one transfer too late. `prefetch` takes the item **first**, exactly
as OpenTitan's `spi_device_driver::get_and_drive()` does (`get_next_item(req)`, and only
*then* `wait (!csb)`).

## The mutations — this bench exists to fail

| mutation | result |
|---|---|
| *(none)* | **TEST PASSED — 177/177** |
| `respond: prefetch` → `on_request` | **171 UVM_ERROR**, `DEAD_RESPONDER` — the driver never gets an item in time to drive a single frame |
| empty the `drive_transfer` seam | **`UVM_FATAL EMPTY_TRANSFER`** |
| delete `.sck(sck)` from `dut_connections` | `quick-uvm generate` **refuses**, exit 1 |

The `EMPTY_TRANSFER` guard sits **outside** the pragma, deliberately. Put it inside and
emptying the seam deletes the guard — which is exactly what happened first time round: the
bench then **hung for five minutes** instead of failing, because the driver spun at a single
timestep. A hung bench reports nothing at all, which is worse than a failing one. The guard
catches the one thing an empty seam cannot fake: a transfer that consumes **zero time**.

## What is checked

The predictor derives the expected `rx_byte` from the **frame index**, through its own copy
of the device's payload function — never from the `miso` observed on the wire. Predicting
from the observed value would be a tautology that a device sending the *wrong* byte would
still pass. Plus `NO_FRAMES` (the host completed zero frames) and the driver's generated
`DEAD_RESPONDER`.

## What is hand-written

The SPI protocol itself: the MISO shift loop in `drive_transfer`, and the payload in
`prefetch_response`. **No generator emits protocol logic** — OpenTitan's own `uvmdvgen` ships
an empty `get_and_drive()`. QuickUVM generates the seam, the timing contract, the clock
model, and three independent liveness checks. It does not generate SPI.

## Run

    make -C gen regress
