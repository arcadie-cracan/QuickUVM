# entropy_src windowed statistics — does the predictor seam scale from per-transaction to per-window? (a build)

**Target:** OpenTitan `entropy_src` health tests (the Adaptive Proportion test + the alert path).
**Kind:** a *build* — a committed, Xcelium-green, mutation-proved example (`examples/es_adaptp/`),
not a paper probe. **The question:** K0's predictor is `predict(item) → exp` — one transaction in,
one expected out. `entropy_src`'s health tests are **windowed**: N raw samples accumulate and **one**
pass/fail verdict emerges per window (an N:1 statistic), with a **second** cross-window level —
consecutive failing windows latch an alert, a passing window resets the run. Does the generated
scoreboard scale to that, or does the 1-in-1-out seam break?

Each claim is tagged **[C]** expressible today (grounded on the green build), **[P]** possible only
as hand-written seam logic, or **[I]** a genuine gap.

## The one-line result

It scales — the sixth over-pessimistic "it breaks" prediction to dissolve on contact with a
simulator — but only in **one** scoreboard shape, and the *shape asymmetry* is the finding. A
**single-stream** scoreboard expresses the windowed N:1 statistic by accumulating in predictor state
and overriding the verdict only at the window boundary; a **two-stream** scoreboard, being strictly
1:1, cannot. The predictor has no clock handle, so the window *boundary* is taken from the DUT's own
strobe — made safe by an independent window-length liveness, not left as a guard trusting itself.

## What the block actually is (verified from source)

Grounded in `entropy_src_adaptp_ht.sv`, `entropy_src.hjson`, `entropy_src_scoreboard.sv`, and the
[Theory of Operation](https://opentitan.org/book/hw/ip/entropy_src/doc/theory_of_operation.html):

- **Adaptive Proportion (ADAPTP):** over a window, **count the 1-bits** (`threshold_scope`=summed);
  `fail_hi = count > HI`, `fail_lo = count < LO` (**strict**). Thresholds are CSR-programmed
  (`ADAPTP_HI/LO_THRESHOLD`).
- **Window:** `FIPS_WINDOW` = **512 symbols** (× `RngBusWidth`=4 = 2048 bits); bypass = 384 bits.
- **Alert accumulation:** `ALERT_SUMMARY_FAIL_COUNTS` counts **consecutive** failing windows,
  **auto-cleared after any passing window**, and raises a recoverable alert at `ALERT_THRESHOLD`
  (reset 2).
- **The DV scoreboard predicts in pure SV, accumulate-then-compute per window** (`calc_adaptp_test`
  / `evaluate_adaptp_test`, a queue of samples per window; REPCNT is a per-sample running counter).
  This is exactly the "windowed statistic, one pass/fail per N samples" shape — not per-transaction.

`examples/es_adaptp/rtl/es_adaptp.sv` is a faithful shrink: 4-bit symbols, 1-bit count, strict
`>`/`<`, the consecutive-fail alert with reset-on-pass. Two simplifications, neither touching the
windowing question: the window is 8 not 512 (a sim must finish; the N:1 shape is identical at any N),
and thresholds are parameters not CSRs (an orthogonal, already-expressible RAL concern — `regfile`,
`ahb_regs`).

## The finding: the scoreboard *shape* decides it

The core mechanic (verified in `quick_uvm/templates/`):

- **[I] two-stream cannot do N:1.** A two-stream scoreboard wires source→predictor and
  monitor→comparator; the comparator matches **one expected against one actual, in order**
  (`expfifo.get` then `outfifo.get`). Feed it N raw samples against 1 verdict/window and the streams
  **desync**. Its reference model does **not** `copy(t)`, so there is no copy-through to lean on
  either. A windowed statistic is structurally unexpressible in this shape.
- **[C] single-stream does, via copy-through.** A single-stream scoreboard feeds the *same*
  monitored transaction to **both** the predictor and the comparator's "actual", and `predict()`
  begins with `extr.copy(t)`. So the predictor **accumulates the window in its own members** and
  **overrides the verdict fields only on the boundary cycle**; every other cycle is copy-through
  (expected == actual, trivial pass). The N:1 statistic is folded into the 1:1 cadence — the check
  bites once per window. `hmac` already proved the stateful-predictor shape; this proves the
  **fixed-window** case, which is the purer windowed statistic.
- **[P] the boundary comes from the DUT, made safe by two independent liveness checks.** The
  predictor has no clock/cycle handle (`predict(item)→item`), so it cannot count cycles to *define*
  the window; it takes the boundary from the DUT's `window_done` strobe. On its own that is a guard
  trusting only itself. The predictor also counts samples independently and fails **both** a boundary
  at the wrong count (`m_scount != WINDOW`, mutation #2) **and** a boundary that never comes
  (`m_scount > WINDOW+1` off-boundary, mutation #4). The second check is the one that matters and the
  one an earlier version of this bench got wrong — it had put the length check *inside* the
  `if (window_done)` guard, so a stuck-low strobe passed silently; an adversarial review caught it,
  and moving the check outside the guard closed it. A boundary strobe you key off must be checked
  from outside its own guard.

## The build proves it

`adaptp_test` 56/56, `rand_test` 160/160, **0 errors / 0 warnings**; `make regress` 4/4 (2 tests ×
2 seeds); verible clean; byte-identity gated. **Mutation-proved four ways** (`MUTATIONS.md`), golden
model unchanged throughout: tighten `HI` 24→23 → **exactly one** window flips (the count-24 edge);
`WINDOW` 8→7 → the length liveness fires every window; disable the alert latch → 33 vectors fail (the
cross-window level); force `window_done` low → the off-boundary liveness fires (a never-strobing DUT
is caught, not silently passed). The statistic is computed independently from the accumulated
samples, so none of these could be caught by a scoreboard echoing the DUT.

## What "run it, don't reason" — and an adversarial review — caught

- **Input/output split-edge skew (×2).** The monitored `sample` (a driven input) lagged the
  health-test outputs by a cycle, so the window summed the wrong samples — the same alignment
  `cdc_fifo` hit, fixed with the `sample_dut_additional` re-sample. The **`emit_when` qualifier
  `valid` had the identical skew** and was captured a cycle before the sample it gates: harmless with
  constant `valid==1` (it merely dropped the first live sample), but a desync on any *gapped* valid
  stream — exactly the case `emit_when:valid` exists for. Surfaced by the adversarial review, fixed
  by re-sampling `valid` too; after which no sample is dropped and every window (including the first)
  is checked. A generated monitor that re-aligns one qualified input should re-align **all** of them.
- **The stuck-low `window_done` gap** (above): the first cut trusted the boundary strobe from inside
  its own guard; the review flagged it, and the off-boundary liveness closed it (mutation #4).

## Threats to validity

- **Built and run** (unlike the alert_handler probe) — Xcelium-green and mutation-proved, so the
  positive claim is by construction. The [I] two-stream claim is proven by the framework code
  (in-order comparator + no `copy(t)` in the two-stream model), not merely by not-trying.
- **Small window / parametric thresholds** are disclosed above; neither changes the N:1 shape, which
  is what is under test.
- **Mid-window outputs are not checked** — the verdict fields are compared only at the boundary
  (copy-through off-boundary), so a DUT driving a garbage *running* count or a spurious mid-window
  `test_fail` escapes. Those outputs are spec-meaningful only at `window_done`; a mid-window
  "outputs idle" assertion would close it. Disclosed in `MUTATIONS.md`.
- **One test of four.** ADAPTP is the representative windowed test; BUCKET/MARKOV are the same
  accumulate-then-threshold shape (max-bucket / transition counts), REPCNT is a per-sample running
  counter (strictly easier). The finding generalizes to the windowed family; the continuous tests
  are a subset of what is shown.
- **Adversarially reviewed.** A three-dimension review (is the check real? are the claims accurate?
  is the shrink faithful?) verified both halves of the finding against the framework code, confirmed
  the RTL and directed arithmetic, and produced the two fixes above — the write-up reflects the
  post-review state, not the first draft.

## What this argued for — now built

The build named a sharp edge worth a first-class answer: a **windowed-scoreboard** shape
(accumulate-N-emit-1) so the single-stream copy-through trick and the DUT-strobe-plus-dual-liveness
pattern are not re-derived by hand each time. That is now the **`window:` feature** (a `window:
{boundary, length}` block on a single-stream scoreboard; see `docs/parity_roadmap.md`). This bench
now *uses* it: the counter, boundary keying, copy-through cadence, and — the part hand-written here
that was wrong twice — the dual liveness are generator-carried, and the seams hold only the ~15
lines of ADAPTP domain logic. The feature answers the **cycle-accurate temporal-checking** axis the
alert_handler probe named — "the predictor cannot count cycles to define a window," resolved by
keying off the DUT's own strobe and guarding it from *outside* with the length liveness.
