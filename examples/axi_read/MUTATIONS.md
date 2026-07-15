# axi_read — mutation proofs

A passing responder proves nothing until it can fail. Each mutation below is a one-line change
to the generated bench that a *correct* pipelined responder must turn red. All run on Xcelium.

## Baseline (unmutated) — PASS

```
[MASTER] issue order = [ 4 3 2 1 0 ]  recv order = [ 4 0 1 2 3 ]  got=5/5  cross-id reorders=4
UVM_ERROR : 0   UVM_FATAL : 0
```

Five requests floated, all five answered, out of order by id. Green.

## M1 — break the drain (the T6 strand) → STRANDED_REQUESTS, FAIL

In `gen/rd_responder_seq.svh`, change the DRIVE thread's `forever begin` to a one-shot `begin`
(answer one response, then stop — the exact failure the on_request shape has):

```
UVM_ERROR .../rd_sequencer.svh(44) [STRANDED_REQUESTS] pipelined responder accepted 5
  request(s) but answered only 1 — the tail of a burst was STRANDED. ...
UVM_ERROR : 1
[MASTER] ... recv order = [ 4 x x x x ]  got=1/5
```

This is the point of the whole feature: a stranded burst is caught by a **UVM_ERROR**, not passed
silently. `DEAD_RESPONDER` alone cannot catch it — the responder *did* drive one response, so it
is not dead; it is stranded. `STRANDED_REQUESTS` (accepted != answered) is the complementary guard.

## M2 — wrong reorder policy → no reorder (proves the ordering is real)

In `gen/rd_responder_seq.svh`, flip the cross-ID policy from lowest-first to highest-first
(`ready[i] < pick` → `ready[i] > pick`). With the descending issue order, highest-first drains in
issue order, so the reorder disappears:

```
[MASTER] issue order = [ 4 3 2 1 0 ]  recv order = [ 4 3 2 1 0 ]  got=5/5  cross-id reorders=0
[MASTER] all 5 beats arrived in ISSUE order — no cross-id reorder occurred.
```

The baseline's reorder is therefore produced by the policy, not by luck. (This mutant still passes
the *UVM* verdict — all five are answered — because the reorder assertion is the DUT master's
self-check; the strand/liveness is the UVM-side guard. Both are exercised.)

## Note on the read latency

`gen/rd_driver.svh`'s `drive_item_additional` seam models a slave read latency (`repeat (8)
@vif.cb1`). Remove it and the slave answers each request before the next lands, so no backlog
accumulates and there is nothing to reorder (`recv == issue`). The latency is what makes the
out-of-order behaviour observable — it is a property of the DUT/scenario, not of the feature.
