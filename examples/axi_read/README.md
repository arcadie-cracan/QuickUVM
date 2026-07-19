# axi_read — the pipelined, multi-outstanding, out-of-order responder

**The DUT is an AXI-read master; the testbench is the slave.** The master floats several read
requests (AR beats) *before any is answered*, and the slave returns the read data (R beats)
**out of order by `arid`**. This is the shape PULP's `axi_rand_slave` has and the one the T6
campaign target found QuickUVM could not express — until now.

```yaml
agents:
  - name: rd
    mode: responder
    request_valid: arvalid   # the DUT asserts a read-address request
    respond: pipelined       # multi-outstanding, out-of-order
    reorder_by: arid         # per-ID queues: same-id in arrival order, cross-id reordered
    ports:
      inputs:  [rvalid, rid, rdata, rlast]        # DRIVE = the R (response) channel
      outputs: [arvalid, arid, araddr, arlen]     # SAMPLE = the AR (request) channel
```

## Why `on_request` cannot do this

The default `respond: on_request` sequence answers **one response per incoming request**
(`get -> respond -> get`). Buffering is free — the request FIFO is unbounded — but the response
path strands the burst: after draining the backlog it blocks on a *new* request that never
comes. See [`docs/t6_axi_outstanding_assessment.md`](../../docs/t6_axi_outstanding_assessment.md).

## How `pipelined` does

The responder sequence forks **two threads** (the `axi_rand_slave` accept/serve split):

```
ACCEPT (forever):  request_fifo.get(req)  ->  id_q[req.arid].push_back(req)   // buffer, never blocks the drive side
DRIVE  (forever):  wait(outstanding>0)    ->  pick a ready id  ->  pop_front  // drain the backlog, do NOT block on the bus
                                          ->  <response_logic seam>  ->  start_item/finish_item
```

- **Same-ID** responses stay in arrival order (`pop_front`); **cross-ID** is free to reorder —
  the AXI ordering rule.
- The cross-ID policy is **lowest-ready-id-first** by default; `reorder_policy:` selects
  `priority` / `round_robin` / `random` (see [`../axi_reorder/`](../axi_reorder/)).
- The `response_logic` seam is **identical to `on_request`**, so flipping between the two shapes
  preserves whatever you wrote there.

## What the run shows (Xcelium)

The master floats five requests in **descending** id order and the slave models a read latency,
so a backlog accumulates and the lowest-id-first policy drains it in **ascending** order:

```
[MASTER] issue order = [ 4 3 2 1 0 ]  recv order = [ 4 0 1 2 3 ]  got=5/5  cross-id reorders=4
```

- `got=5/5` — every outstanding request is answered; **no strand**.
- `recv != issue` — a genuine, deterministic (seed-independent) cross-ID reorder.

## Two liveness guards, both generated (not seams)

A responder can pass while doing nothing — the silent-pass trap. Two checks fail the bench
instead:

- **`DEAD_RESPONDER`** (driver) — fires if the responder drove *nothing*.
- **`STRANDED_REQUESTS`** (sequencer) — fires if `accepted != answered`, i.e. it answered *some*
  of a burst and stranded the tail. This is the check that makes the T6 gap impossible to ship
  silently. See [`MUTATIONS.md`](MUTATIONS.md).

Those guard *delivery*. The **out-of-order** property (the point of this bench) is guarded by a
**UVM oracle** in the monitor (`RD_CHK`): every `R` beat matches an outstanding id and a cross-id
reorder actually occurred — so a degeneration to in-order (remove the drive latency) raises a
`UVM_ERROR`. Without it the reorder is only in the DUT's `$error`/`$display`, invisible to the
UVM-severity `make regress` verdict — the silent-pass this example was hardened against.

## Boundary

This is the AXI **read** channel-pair (AR→R). A faithful full 5-channel AXI VIP (AR+AW, R+B, atomics)
is a larger, two-agent build — gap-by-design, per the T6 assessment §4. The genuine capability
question was the out-of-order responder, and that is what `respond: pipelined` answers.

## Run it

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
# or the seed regression:
cd ../gen && make regress
```
