# hybrid_alert — mutation proofs

Two paths, two proofs. Each mutation is reverted after. Baseline: **TEST PASSED — 620 Ran /
620 Passed, 0 errors.**

## A — the proactive path (scoreboard has teeth)

Mutation: the DUT latches a corrupted alert payload — `last_adata <= adata ^ 8'h01`.

Result: **FAILED** — the single-stream scoreboard flags every alert (`Expected last_adata=1,
Actual last_adata=0`, …). The proactive stimulus is genuinely checked, not just driven.

## B — the reactive path, and why the liveness must be un-maskable (the point)

Mutation: the responder sequence hangs (`wait(0)` before it answers) — a **dead ping-responder**
— while the proactive alert sequence keeps running.

Result: **the test FAILS, but only because of the request-FIFO drain**:

```
UVM_ERROR sndr_sequencer.svh(42): [DEAD_RESPONDER] 129 observed request(s) were never
          answered — the responder is dead or lagging. A hybrid's liveness is the
          request-FIFO drain, not the driver's drive count (proactive stimulus inflates that).
*** TEST PASSED - Vectors: 522 Ran / 522 Passed ***     <- the comparator passed
UVM_ERROR : 1                                            <- the drain liveness failed it
```

Read that carefully. The comparator says **PASSED** (the alerts kept latching correctly), and
the driver's own `DEAD_RESPONDER` (`m_responses != 0`) never fired — **it was masked**, because
the proactive alerts drove the bus and inflated the count. If the drain check were not generated,
this stone-dead responder would have gone **green**. The request-FIFO drain — which proactive
stimulus cannot touch — is the only thing that caught it, and that is the whole reason a
`proactive: true` responder needs a liveness the naive relaxation does not have.
