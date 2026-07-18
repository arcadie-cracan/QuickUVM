# es_adaptp — mutation proofs

A passing windowed scoreboard proves nothing until it is shown it can *fail*. Each mutation below
edits `rtl/es_adaptp.sv`, runs `+UVM_TESTNAME=adaptp_test`, and is then reverted. The golden model
in `gen/es_adaptp_reference_model.svh` is **unchanged** throughout — so a caught mutation is the
independent windowed statistic biting, not the model tracking the DUT.

Baseline (unmutated): **TEST PASSED — 56 Ran / 56 Passed, 0 errors.**

| # | Mutation | Expected | Observed |
|---|----------|----------|----------|
| 1 | `HI` 24 → 23 | the HI-edge window (`0x7`×8 = 24) flips PASS→FAIL; golden still expects PASS | **FAILED, exactly 1 vector** (the HI-edge window) — surgical |
| 2 | `WINDOW` 8 → 7 | the DUT closes windows a sample early; the predictor expects 8 | **FAILED** — `ADAPTP_WIN "window closed after 7 samples, expected 8"` every window |
| 3 | alert latch disabled (`alert_set` forced 0) | the DUT never raises `alert`; golden expects it after 2 consecutive fails | **FAILED, 33 vectors** — the alert-window check and every later latched-alert compare |
| 4 | `window_done` forced `1'b0` (never strobes) | the DUT never closes a window; the golden model must not accumulate forever and pass | **FAILED** — `ADAPTP_WIN "no window boundary after 10 samples (expected every 8)"` |

## Why these four

- **#1 (threshold)** proves the *statistic* is real and independent: tightening `HI` by one flips
  only the window whose count sits exactly on the boundary (24). A scoreboard that echoed the DUT
  could never catch this.
- **#2 (moved boundary)** and **#4 (no boundary)** together prove the window timing is checked from
  *both sides* of the strobe the verdict is keyed off. The verdict fires on the DUT's `window_done`,
  but `#2` (`m_scount != WINDOW` at a boundary) catches a boundary at the wrong sample count, and
  `#4` (`m_scount > WINDOW+1` off-boundary) catches a boundary that never comes. So the strobe is
  **not a guard trusting only itself** — a stuck-low `window_done` fails rather than silently
  copy-through, which an earlier version of this bench got wrong.
- **#3 (alert latch)** proves the *cross-window* level: the consecutive-fail accumulation and the
  latched alert are independently modelled, so a DUT that fails to escalate is caught.

## Residual, by construction

The verdict fields are only checked at the window boundary; a DUT that drives a *garbage* running
`ones_cnt` or spuriously asserts `test_fail` on a **mid-window** cycle would not be caught (those
outputs are copy-through until the window closes, and are spec-meaningful only at `window_done`).
Adding a mid-window "outputs must be idle" assertion would close this; it is out of scope for a
probe of the *windowing* seam.
