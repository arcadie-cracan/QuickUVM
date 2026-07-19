# axi_handshake — the AXI epic, slice 3: the valid/ready handshake

The first slice that needed a **framework feature**, not just a seam. The earlier examples are
valid-only (a request is a pulse); real AXI channels are two-sided valid/ready handshakes where
`valid` is **held** until `ready`. See [`docs/axi_epic_assessment.md`](../../docs/axi_epic_assessment.md).

## The feature: `request_ready:` (level capture)

The responder monitor normally publishes a request by **edge-detecting** `request_valid`. That
is wrong for a handshake: a master holds `arvalid` and issues requests **back-to-back** (a new
`arid` each cycle the slave accepts), so an edge-detect sees only the *first* — exactly the
under-count [T6](../../docs/t6_axi_outstanding_assessment.md) flagged. Opt-in `request_ready:`
switches the monitor to a **level** capture — one publish per cycle `valid && ready` are both
high:

```yaml
mode: responder
request_valid: arvalid
request_ready: arready     # capture on the handshake, not the edge
```

```systemverilog
// generated when request_ready is set:
if (tr.arvalid && tr.arready) request_ap.write(tr);   // one publish per accepted cycle
```

Opt-in and byte-identical when absent (the edge-detect is unchanged). A handshake needs `valid`
and `ready` **co-observed at one edge**; when `request_ready` is a line the slave itself drives
(the default split-sampling would read it a cycle early), the generated monitor re-samples it raw
with the DUT outputs automatically — the same fix inouts already get, so the feature works from
generated code with no hand seam.

## What runs

`rtl/axi_handshake.sv` is a read master that **holds** `arvalid` and issues N=4 requests
back-to-back, and drives `rready` low every third cycle (response backpressure). The slave
captures every request on the handshake and answers each, holding `rvalid` until `rready`:

```
AR accept #0..3 arid=1,2,3,4    (back-to-back, one per cycle)
R  accept #0..3 rid=1,2,3,4     (spaced by the rready backpressure)
[HS MASTER] AR accepted=4/4  R accepted=4/4
```

Green on Xcelium: `0 UVM_WARNING / 0 UVM_ERROR / 0 UVM_FATAL`.

## The seams the handshake needs

The AR request-capture co-sampling is automatic (above). Two things stay in seams — protocol
precision, which QuickUVM never generates:

- **The R-channel hold** (`rd_driver.svh`). `while (!vif.cb1.rready) @vif.cb1;` keeps `rvalid`
  asserted until the master accepts, then drops it — the response-side backpressure.
- **The oracle's R co-sampling** (`rd_monitor.svh`). The oracle also watches the *R* handshake
  (`rvalid && rready`); `rvalid` is driven, so it re-samples it raw with the outputs — the same
  alignment the feature does for the request, done by hand for this bench-specific check.

## The verdict is carried by a UVM oracle

The regression verdict is UVM-severity based, so the master's `$error` is invisible to it (the
[axi_read_burst](../axi_read_burst/) lesson). The monitor counts AR and R transfers
**independently of the request-publish** and `check_phase` fails if they differ — a lost
back-to-back request means fewer responses than requests accepted.

## Proved it can fail

| Mutation | Break | Verdict → FAIL via |
|---|---|---|
| M1 | revert the level capture to edge-detect (feature off) | oracle: "R transfers (1) != AR transfers (4)" — back-to-back collapsed to 1 |
| M2 | drop `rvalid` without waiting for `rready` (no R-hold) | oracle: "R transfers (3) != AR transfers (4)" — a beat lost |

M1 is the one that matters: it proves the **level-capture feature** is load-bearing — with an
edge-detect only the first of the four back-to-back requests survives.

## Scope

Single outstanding request pattern with back-to-back AR; `arready` is always-ready here
(request backpressure — `arready` gaps — is a trivial extension). Bursts × handshake, and the
unified read+write agent, remain later epic slices.

## Layout
- `rtl/axi_handshake.sv` — the handshake read-master DUT.
- `axi_handshake.yaml` — responder with `request_valid` + `request_ready`.
- `gen/` — user-filled seams: `rd_monitor.svh` (co-sampling + oracle), `rd_driver.svh`
  (always-ready init + R-hold).
- `sim/xrun.f` — Xcelium filelist.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
