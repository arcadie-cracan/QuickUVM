# es_adaptp — a windowed health-test statistic (OpenTitan entropy_src)

**Can QuickUVM's predictor seam express a WINDOWED statistic — N raw samples accumulate and
ONE pass/fail verdict emerges per window (an N:1 statistic), not one-verdict-per-sample?**
Yes — and it is now a first-class QuickUVM feature, the **`window:` scoreboard** (this bench is its
proof and its example). It models OpenTitan `entropy_src`'s **Adaptive Proportion** health test:
over a window of symbols, count the 1-bits; the window **fails** if the count is `> HI` or `< LO`
(strict, like the RTL). A second, cross-window level sits on top: **consecutive failing windows**
accumulate and, at `ALERTN`, latch an **alert** — a passing window resets the run (OpenTitan's
`ALERT_SUMMARY_FAIL_COUNTS` / `ALERT_THRESHOLD`).

## The feature: single-stream copy-through does it; two-stream cannot

K0's predictor is `predict(item) → exp` — **one transaction in, one expected out**. A windowed
test is **N:1**. The resolution is the scoreboard *shape*, and it is what the `window:` feature
encodes:

- A **two-stream** scoreboard (source→predictor, monitor→comparator) is strictly **1:1**: the
  comparator pairs one expected with one actual in order (`expfifo.get` then `outfifo.get`). Feed
  it N raw samples against 1 verdict per window and the streams **desync**. It cannot express N:1 —
  the schema rejects `window` with a `monitor`.
- A **single-stream** scoreboard feeds the *same* monitored transaction to **both** the predictor
  and the comparator's "actual", and `predict()` starts with `extr.copy(t)`. So the predictor can
  **accumulate the window in its own state** and **override the verdict fields only on the boundary
  cycle**; every other cycle is copy-through (expected == actual, a trivial pass). The N:1 statistic
  is folded into the 1:1 cadence — the check *bites* exactly once per window.

```yaml
analysis:
  scoreboards:
    - name: sb
      source: es
      window: {boundary: window_done, length: 8}   # the DUT strobe + samples/window
```

The `window:` block makes QuickUVM generate the sample counter, the boundary keying off
`window_done`, the copy-through cadence, and the **dual liveness** (below); the reference model's
`window_accumulate` / `window_verdict` seams hold only the ADAPTP domain logic (~15 lines). The
statistic is computed **independently** from the accumulated samples (not echoed from the DUT):
the predictor sums `popcount(sample)` across the window and compares its own `ones_cnt` /
`test_fail` / `alert` against the DUT's. The window **boundary** is taken from the DUT's own
`window_done` strobe (which delimits the windows in the emitted stream), but that is **not a guard
trusting only itself**: two independent liveness checks make both failure modes fail rather than
copy-through — `m_scount != WINDOW` at a boundary catches a **moved** boundary, and `m_scount >
WINDOW+1` off-boundary catches a **stuck/never-strobing** `window_done`. See
`gen/es_adaptp_reference_model.svh`.

**Result:** `adaptp_test` 56/56, `rand_test` 160/160, **0 errors / 0 warnings**; `make regress`
4/4 (2 tests × 2 seeds). Mutation-proved four ways — see [MUTATIONS.md](MUTATIONS.md).

## What "run it, don't reason" (and an adversarial review) caught

1. **Input/output split-edge skew.** The monitored `sample` (a driven input, captured at posedge
   N) lagged the health-test outputs (sampled an edge later) by one cycle, so the predictor's window
   summed the wrong samples. Fixed by re-sampling `sample` at the output edge in the
   `sample_dut_additional` seam — the same input/output alignment `cdc_fifo` needed.
2. **The `emit_when` qualifier had the same skew.** `valid` (the emit gate, also a driven input) was
   captured a cycle before the `sample`/verdict it qualifies. With constant `valid==1` this only
   dropped the first live sample (a benign startup artifact); on a **gapped** valid stream it would
   desync every gap. Surfaced by an adversarial review of this bench, then fixed by re-sampling
   `valid` at the output edge too — after which no sample is dropped and *every* window (including
   the first) is checked.
3. **The stuck-low `window_done` gap.** An earlier version put the only window-length check *inside*
   the `if (window_done)` boundary guard — so a DUT whose strobe never fired would accumulate
   forever and silently pass. Closed with the off-boundary `m_scount > WINDOW+1` liveness (mutation
   #4). A boundary strobe you key off must be checked from *outside* its own guard.

## Faithfulness (and what is deliberately held out)

The statistic (1-bit count, strict `>`/`<`), the consecutive-fail alert with reset-on-pass, and
the 4-bit symbol match `entropy_src`. Two simplifications keep the **windowing** question — the
thing under test — clean, and neither touches it:

- **Window = 8, not 512.** A small window just lets a sim finish; the N:1 accumulation shape is
  identical at any N.
- **Thresholds are parameters, not CSR-programmed.** The real block programs `ADAPTP_HI/LO_THRESHOLD`
  via TileLink; that is an orthogonal, already-expressible RAL concern (see `examples/regfile`,
  `examples/ahb_regs`), held out so the scoreboard is legible.

## Run

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=adaptp_test   # directed windows (the mutation target)
xrun -f xrun.f +UVM_TESTNAME=rand_test     # random entropy; every window's verdict checked
# or the seed regression:
cd ../gen && make regress
```
