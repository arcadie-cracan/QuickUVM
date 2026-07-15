# spi_host — the mutations, as recipes

Every simulation claim made about this example is reproducible from here. A claim in a write-up
with no recipe behind it is not evidence, and this project has published two that turned out to be
false.

Run from `sim/` unless stated. The verdict is read from the **UVM severity block**, never from the
exit code — `xrun` exits 0 even with UVM_ERRORs.

    xrun -f xrun.f +UVM_TESTNAME=rand_test -svseed 1 -l sim.log
    awk '/Report counts by severity/,/Report counts by id/' sim.log

## Baseline

    make -C ../gen regress                     # rand_test x 3 seeds -> 3/3

    for m in 0 1 2 3; do                       # all four CPOL/CPHA modes
      xrun -f xrun.f +UVM_TESTNAME=rand_test \
           +SPI_CPOL=$((m/2)) +SPI_CPHA=$((m%2)) -svseed 1
    done                                       # -> 0 UVM_ERROR in each

Baseline: **2674 vectors, 0 UVM_ERROR.**

---

## M3 — `prefetch` is load-bearing on real silicon *(the reason T2 exists)*

In `spi_host.yaml`: `respond: prefetch` → `respond: on_request`. Regenerate with `--allow-drop`
(the seam moves from the driver to the sequence), then port the same device protocol to the
`response_logic` + `drive_item_additional` seams.

**Expected: `TEST FAILED` — 8/8 RXDATA vectors fail, 10 UVM_ERROR, `[DEAD_RESPONDER]`.**

`on_request` waits for the monitor to publish a request — which happens at *frame end* — so the
device never drives during the frame at all.

---

## M2 — the check is real, not an echo

In `gen/sdio_responder_seq.svh`, `prefetch_response`:

    rsp.miso_byte = 8'hA5 ^ 8'(m_sent);          ->   ... ^ 8'h01;

**Expected: `TEST FAILED` — 8/8 RXDATA vectors fail (9 UVM_ERROR).**

The predictor derives the expected byte from the frame index through its own copy of the device
model — never from anything observed on the wire. Predicting from the observed value would be a
tautology that a device sending the wrong byte would still pass.

## M2b — the pull-ups do not fake a device

In `gen/sdio_driver.svh`, `drive_transfer`:

    vif.sd_oe = 4'b0010;                         ->   vif.sd_oe = 4'b0000;   // never drive

**Expected: `TEST FAILED` — 8/8 fail.** The host reads the floating (pulled-up) line, not our byte.

---

## M1 — the DUT's own reset state is a trap

In the directed sequence (`gen/spi_host_ot_tb_pkg.sv`, `regbus_prog_seq::body`), drop
`CONTROL.OUTPUT_EN` (bit 29):

    beat(RControl, 1'b1, (32'h1 << 31) | (32'h1 << 29) | 32'h7f);
    ->  beat(RControl, 1'b1, (32'h1 << 31) | 32'h7f);

**Expected: `TEST FAILED` — 8/8 fail, 10 UVM_ERROR, `[DEAD_RESPONDER]`.**

`OUTPUT_EN` resets to 0 and gates `sck`, `csb` and every `sd` lane, so the DUT drives **nothing** —
and with pull-ups the bus floats to `0xff` and looks quiet and legal. **No X, no error, no protocol
violation.** A check asking only "is there an X on the bus?" passes while testing nothing.

**Note which guard fires — `DEAD_RESPONDER`, not `NO_RXDATA`.** With `csb` never falling, the device
driver parks forever inside `drive_transfer` and drives ZERO transfers; but the register bus still
works, so RXDATA reads still happen and `NO_RXDATA` stays quiet.

**This is the exact scenario PR #59 was written for.** Before that fix, `DEAD_RESPONDER` counted
items *fetched* rather than transfers *driven* — a driver parked forever on `@(negedge csb)` had
fetched an item, so it would have reported itself alive and the guard would have stayed **silent
while the device was stone dead**. That fix was made on a prediction from this target's build spec;
this is the real thing it predicted, firing correctly.

(I first wrote "`NO_RXDATA` fires" in this file, from reasoning rather than running. It is wrong.
Every recipe here has since been executed.)

The same trap at RTL level is in `sim/tb_reg_smoke.sv` (Slice 0b) — where it was first caught,
before a single line of UVM existed.

---

## M4 — per-lane output enable is load-bearing *(and the first attempt at this FAILED)*

In `gen/sdio_driver.svh`, replace **every** `vif.sd_oe = 4'b0010;` with `4'b1111` — the device
drives all four lanes, which is exactly what a **scalar** output enable forces.

**Expected: 8 × `MOSI_MISMATCH` — "the device received 00, the host sent 5a".**

In standard mode the host owns sd[0] (MOSI) and we own sd[1] (MISO), **at the same instant**. Drive
lane 0 as well and we fight the host: its MOSI resolves against our 0 and the device receives
garbage.

**This mutation passed the first time it was run**, and that was the finding. The bench checked only
what the **host** received (RXDATA) and never what the **device** received — so half of a
full-duplex transfer was unverified, and lane-0 contention lives in exactly that half. The device's
MOSI check (`host_byte()` in `sdio_driver.svh`) closes it, and only then does this mutation bite.

Until this bench, **per-lane `inouts` had never been mutation-proved anywhere**: `examples/spi_device`
declares *scalar* miso/mosi and has no `inouts:` at all.

## M7 — per-lane ownership is load-bearing in DUAL, too *(a scalar enable cannot make `0011`)*

Run a dual read and mutate the device's enable to the **standard** subset:

    xrun -f xrun.f +UVM_TESTNAME=rand_test +SPI_SPEED=1 -svseed 1     # baseline: 0 UVM_ERROR
    # in gen/sdio_driver.svh, the DUAL branch:  vif.sd_oe = 4'b0011;  ->  4'b0010;

**Expected: 8/8 fail.** In dual RdOnly the DUT reads `sd[1:0]` (spi_host_shift_register.sv:60); the
device must drive both lanes (`0011`). Drop to `0010` and `sd[0]` floats to the pull-up, so every
even bit reads 1 and RXDATA mismatches. **A scalar output enable — `0000` or `1111` only — cannot
produce `0011`.** With Standard (`0010`, M4) that is two of three required patterns a scalar cannot
express.

## M8 — the dual/quad RX check discriminates lane count

    xrun -f xrun.f +UVM_TESTNAME=rand_test +SPI_SPEED=2 -svseed 1     # baseline: 0 UVM_ERROR
    # in the QUAD branch:  vif.sd_oe = 4'b1111;  ->  4'b0011;

**Expected: 8/8 fail** (`sd[3:2]` float). Note quad's `1111` *is* scalar-achievable, so this proves
the check works, **not** that per-lane is required for quad specifically. Dual (M7) is the load-bearing
per-lane proof; quad is corroboration.

## M5 — the modes are REAL, not aliased to mode 0

Four green modes prove nothing if `cpol`/`cpha` never reach the DUT: wrong `CONFIGOPTS` bit
positions and every mode silently behaves as mode 0, and all four "pass" for free.

Probe `sck`'s idle level between frames (add to `gen/tb_top.sv`, outside the pragmas — regeneration
will remove it):

    initial begin
      #20000;
      $display("[PROBE] sck idle level = %b", sck);
    end

**Expected: CPOL=0 → `0`; CPOL=1 → `1`.** The modes are distinct.

And the check is live in *each* mode: apply **M2** and run all four — **all four go red** (9
UVM_ERROR each).

---

## M6 — the VENDORED RTL is really under test

In `rtl/vendor/spi_host_shift_register.sv` (OpenTitan's, unmodified — revert afterwards):

    {sr_q[6:0], next_bits[1]}    ->    {sr_q[6:0], ~next_bits[1]}

Run the **Slice 0a** smoke test (no UVM):

    xrun -sv -f core_smoke.f -top tb_core_smoke

**Expected: `FAIL — the host received the device's byte: got c3, expect 3c`.** Restore it and it
passes. The vendored RTL is genuinely under test, and the smoke test can genuinely fail.
