# axi_write — the AXI epic, slice 1: the WRITE channel (AW + W → B)

The counterpart to [`examples/axi_read`](../axi_read/) (the read channel `AR → R`).
Together they are the first two slices of the **AXI 5-channel VIP epic** — see
[`docs/axi_epic_assessment.md`](../../docs/axi_epic_assessment.md) for the full scope.

The DUT is an AXI-write **master**; the testbench is the **slave** that returns write
responses (`B` beats) **out of order** by id. It reuses the proven pipelined responder
(`respond: pipelined` + `reorder_by`) — the same machinery as `axi_read` — with **one new
idea** the read side did not need.

## The one new thing: two request channels, one response

A read has a single request channel (`AR`) → a single response (`R`). A write has **two**
request channels — the write **address** `AW` and the write **data** `W` — that must be
correlated into one response `B`. AXI4 gives the `W` beats **no id**: the *k*-th `W` burst
pairs with the *k*-th `AW` purely **by order**. So the slave must remember which `AW` each
`W` belongs to.

QuickUVM's responder samples **one** `request_valid` qualifier, so the correlation is done
in the monitor (a seam — hand-written protocol code, which every UVM methodology writes):

```systemverilog
// wr_monitor.svh — class_item_additional
bit [3:0] m_awid_q [$];   // awids of accepted-but-not-completed writes, oldest first

// wr_monitor.svh — sample_dut_additional
if (t.awvalid) m_awid_q.push_back(t.awid);            // a new AW arrives: remember its id
if (t.wvalid && t.wlast && m_awid_q.size() > 0)       // the write completes on its last beat:
  t.awid = m_awid_q.pop_front();                      //   stamp it with the matching id
```

`request_valid: wlast` then fires the request-publish **once per completed write**, carrying
the correlated id. From there it is ordinary `axi_read`: `reorder_by: awid` buffers the
completed writes into per-id queues and drains them lowest-id-first, so `B` comes back
out of order.

### Making the order load-bearing

The `B` beat carries only `bid`+`bresp`, so a bench that checked only "did every id come
back?" would pass for *any* bijection — including a **wrong-order** correlation that pairs each
write's data with the wrong address. To make the AW→W **order** genuinely observable, each `W`
beat carries a self-describing tag: `wdata[3:0]` is the id of the `AW` it belongs to. The slave
checks the tag against the correlated `awid` and returns **`SLVERR`** on a mismatch (that is
what `bresp` is *for*); the master fails on any `SLVERR`. So a mis-ordered pairing is caught
end-to-end — not merely "some id was produced" (see mutation 4 below).

## What runs

`rtl/axi_write.sv` floats N=5 writes with distinct **descending** ids (all `AW` first, then
all `W`), accepts `B` beats in any order, matches each to an outstanding write by `bid`, and
at end of test **fails** if any write was stranded *or* if no cross-id reorder occurred. The
slave drains lowest-id-first, so the descending backlog comes back reordered:

```
[WMASTER] issue = [ 4 3 2 1 0 ]  B recv = [ 4 2 0 1 3 ]  got=5/5  cross-id reorders=3
```

Green on Xcelium: `0 UVM_WARNING / 0 UVM_ERROR / 0 UVM_FATAL`.

## Why the driver models a write-commit latency

`wr_driver.svh` spaces the `B` beats with `repeat (4) @vif.cb1` (a real slave commits the
write before answering). This is **load-bearing, not cosmetic**: the writes complete one at a
time during the `W` phase, so without a commit latency the responder would drain each the
instant it arrives — in issue order, no backlog, no reorder. The latency lets the accept
thread buffer the backlog the lowest-id-first scheduler then reorders. (Remove it and the DUT
correctly fails with "no cross-id reorder" — that is mutation (3) below.)

## Proved it can fail (mutation tests)

A passing test proves nothing until it is proven it can fail. Four mutations, each caught:

| Mutation | Break | Caught by |
|---|---|---|
| 1 | delete the `m_awid_q` pop entirely (no correlation) | tag ≠ awid → `SLVERR`, *and* every `B` collapses to the stale `bid=0` → "bad pairing" |
| 2 | strand one id in the responder | `got=4/5` → DUT master "STRANDED writes" |
| 3 | remove the driver commit latency | `B` in issue order → DUT master "no cross-id reorder" |
| 4 | `pop_front` → `pop_back` (**wrong order**, still a valid bijection) | tag ≠ awid → `SLVERR` "mis-ORDERED AW/W pairing" |

Mutation 4 is the one that matters: it keeps every id distinct (so set-membership alone would
*not* catch it) and only corrupts the **order**. Without the `wdata` id-tag + `SLVERR` check it
passed green — that was a real silent-pass on the slice's headline claim, [found by adversarial
review](../../docs/axi_epic_assessment.md) and fixed here. Mutation 1 is now caught two ways;
note it proves "you must consume the queue," while mutation 4 proves "you must consume it in the
right *order*" — the distinct claim.

The monitor also makes a correlation **underflow** loud rather than silent: a `WLAST` with no
outstanding `AW` raises `AWID_UNDERFLOW` instead of stamping a stale id. Plus the generated
liveness the pipelined responder always emits (`DEAD_RESPONDER`, `STRANDED_REQUESTS`), inherited
unchanged from `axi_read`.

## Scope (honest limits — the next slices)

This slice is **single-beat** writes with the `AW`/`W` valid-only handshake (no `AWREADY`/
`WREADY` backpressure), matching `axi_read`'s simplification. The order-correlation seam
handles multiple `AW` outstanding before their `W` (a real queue), but not yet **bursts**
(`AWLEN > 0`, multiple `W` beats per write — the monitor would count beats to `WLAST`), the
**ready** handshake, or write **interleaving**. Those, plus `AR`+`AW` sharing one agent and
exclusive access, are the remaining epic slices in `docs/axi_epic_assessment.md`.

## Layout
- `rtl/axi_write.sv` — the AXI-write-master DUT (stimulus + self-check).
- `axi_write.yaml` — the responder config (`request_valid: wlast`, `respond: pipelined`,
  `reorder_by: awid`).
- `gen/` — generated TB; the user-filled seams are `wr_monitor.svh` (AW→W correlation),
  `wr_responder_seq.svh` (build `B`), `wr_driver.svh` (single-beat `B` pulse + commit latency).
- `sim/xrun.f` — Xcelium filelist.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
