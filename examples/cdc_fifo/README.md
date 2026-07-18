# cdc_fifo — a cross-domain-integrity scoreboard

**Does QuickUVM's multi-clock (M1) plumbing compose with its two-stream scoreboard (A2) into
a working clock-domain-crossing check?** Yes — proven here. A dual-clock async FIFO
(`rtl/cdc_fifo.sv`, gray pointers + 2-flop synchronizers, the Cummings design) carries data
from a **write** clock domain to a **read** clock domain; a write agent on `wclk` (10 ns) and
a read agent on `rclk` (14 ns) feed a two-stream **in-order** scoreboard that matches the
pushed stream against the popped stream **across the crossing**.

```yaml
clock:
  - {name: wclk, period: 10, unit: ns}
  - {name: rclk, period: 14, unit: ns}   # asynchronous
agents:
  - {name: wr, clock: wclk, emit_when: wxfer, ...}   # source: the pushed words
  - {name: rd, clock: rclk, emit_when: rxfer, ...}   # monitor: the popped words
analysis:
  scoreboards:
    - {name: cdc, source: wr, monitor: rd}           # in-order match, identity predict
```

**Result: 16/16 on Xcelium, 0 warnings** (`make regress` → 2/2). The predictor is identity
(a FIFO is order-preserving and lossless: the Nth word pushed is the Nth popped);
`do_compare` checks `rdata` across the crossing.

## What "run it, don't reason" caught

Building this surfaced two bugs a paper design would have missed:

1. **An RTL combinational loop.** `wxfer = wvalid && wready` fed `wbin_nxt → wgray_nxt →
   wready → wxfer` — a zero-time loop that **deadlocked the simulator in delta cycles** (45 s
   of wall time, 185 ns of sim time). This is exactly why the canonical async FIFO
   **registers** `full`; `rtl/cdc_fifo.sv` does, and documents why.
2. **A monitor input/output misalignment.** When a transaction's **data is a TB-driven input**
   (`wdata`) but its **qualifier is a DUT output** (`wxfer`), QuickUVM's default split-edge
   monitor samples them one cycle apart — injecting a phantom leading source word. Fixed with
   the existing `sample_dut_additional` seam (re-sample `wdata` at the `wxfer` edge), the mirror
   of what `regfile` does for a combinational read.

## Draining, not tolerating

A FIFO legitimately ends with **residual occupancy** (the write ahead of the read), so simply
tolerating unmatched source items would mask a real *dropped* word. Instead the read **drains**:
the write pushes a bounded 16 (its `wvalid` pulses, so it never holds valid and over-pushes),
and the read pops 40× — enough to empty the FIFO. Then `source == monitor == 16` means *no data
was lost across the crossing*. See the custom `cdc_vseq` (parallel push + drain).

## Run

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
# or the seed regression:
cd ../gen && make regress
```
