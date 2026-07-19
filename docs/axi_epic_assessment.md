# The AXI 5-channel VIP epic — scope, slices, and what QuickUVM can express

A full AXI slave VIP is a *protocol-VIP effort*, and the roadmap has always marked it
**gap-by-design** — QuickUVM generates single-block benches, not vendored protocol VIPs.
This doc scopes that epic honestly: it decomposes AXI into slices, records which are **built
and Xcelium-green**, and states — per slice — whether QuickUVM expresses it with *no framework
change* (a seam), or whether it needs new machinery. The T6 finding
([`t6_axi_outstanding_assessment.md`](t6_axi_outstanding_assessment.md)) drew the boundary; this
doc turns it into a build plan and measures progress against it.

## The five channels

AXI4 has five independent valid/ready channels, coupled into two transaction types:

| Channel | Dir (from master) | Role | Transaction |
|---|---|---|---|
| `AR` | master → slave | read address | **read** = `AR → R` |
| `R`  | slave → master | read data + resp | |
| `AW` | master → slave | write address | **write** = `AW + W → B` |
| `W`  | master → slave | write data | |
| `B`  | slave → master | write response | |

The two transaction types decompose cleanly into a **read agent** (`AR → R`, out-of-order by
`id`) and a **write agent** (`AW + W → B`). A full VIP is those two agents plus cross-agent glue
(shared clock/reset, exclusive/atomic access). That decomposition is the epic's slice plan.

## Slice status

| # | Slice | Example | Status | Expressed by |
|---|---|---|---|---|
| 0 | Read channel `AR → R`, multi-outstanding, OoO by id | [`axi_read`](../examples/axi_read/) | ✅ green | `respond: pipelined` + `reorder_by` (T6 feature) |
| — | Reorder policy (priority / round-robin) | [`axi_reorder`](../examples/axi_reorder/) | ✅ green | `reorder_policy` |
| 1 | **Write channel `AW + W → B`**, OoO by id | [`axi_write`](../examples/axi_write/) | ✅ green | **monitor AW→W order-correlation seam** (no framework change) |
| 2 | **Bursts (`ARLEN > 0`, multi-beat `R`, `RLAST`)** | [`axi_read_burst`](../examples/axi_read_burst/) | ✅ green | **driver-seam multi-beat drive** (no framework change) |
| 3 | **Ready-handshake (`AxREADY`/`xREADY`), back-to-back** | [`axi_handshake`](../examples/axi_handshake/) | ✅ green | **`request_ready:` level-capture feature** (the T6 gap closed) + driver-seam R-hold |
| 4 | **Full AXI slave — read agent + write agent on one DUT** | [`axi_slave`](../examples/axi_slave/) | ✅ green | **composition** of slices 0+1, two agents (no framework change) |
| 5 | Bursts × out-of-order (interleaved `R`/`B` beats), exclusive/atomic access | — | ○ | protocol depth in seams (out of scope by design) |

## The write channel (slice 1) — the finding that matters

The write channel is the first place AXI stops looking like the read channel: **two request
channels feed one response**. The write address `AW` and the write data `W` are independent
channels, and AXI4 gives the `W` beats **no id** — the *k*-th `W` burst pairs with the *k*-th
`AW` purely by order.

T6 named this the structural blocker:

> *Two independent request streams. `_check_responder` allows exactly one 1-bit `request_valid`
> and the monitor writes one `request_ap`. One agent samples one request stream.*

Building slice 1 **refined** that. The single-request-stream limit is real, but the write
channel does **not** need two request streams in the framework — it needs the two channels
**correlated into one completed-write request**, and that correlation is ordinary protocol code
in the monitor seam (which every UVM methodology hand-writes):

- the monitor queues each `awid` on `AWVALID`, pops the front on `WLAST`, and stamps the request
  with the matching id;
- `request_valid: wlast` publishes one request per **completed** write;
- from there it is exactly `axi_read`: `reorder_by: awid` drains per-id queues out of order.

So slice 1 ships as a pure **example** — no `quick_uvm/` change — reusing the T6 responder
unchanged. That is the honest headline: **the AW+W coupling is expressible today**, for the
common case (one `W` burst per `AW`, in order), with a seam.

Mutation-proved four ways (delete the correlation → "bad pairing"; strand a write → "STRANDED";
remove the commit latency → "no reorder"; **reverse the correlation order → SLVERR**). The last
one is load-bearing and was earned: adversarial review found that with a `bid`+`bresp`-only `B`
channel and no scoreboard, *any* bijection of ids passed green — the AW→W **order**, the slice's
whole point, was not actually checked. The fix carries a self-describing id-tag in `wdata` that
the slave validates against the correlated `awid`, signalling `SLVERR` on a mis-order — so a
wrong-order pairing now fails end-to-end. (A blunter alternative — a full slave memory model +
read-back scoreboard — would also work but is out of proportion for a valid-only write slice.)

Is cross-id **write** reordering even legal? Yes — `BID` exists precisely to allow it, the
mirror of `RID`. It is *less common* than read reordering (many slaves commit writes in order),
so `axi_write` demonstrates the **capability**; a purely in-order write slave is the trivial
sub-case (drop `reorder_by`).

## Bursts (slice 2) — a multi-beat response, driver-seam only

`axi_read` drives exactly one `R` beat per request; a burst is `ARLEN+1` beats with `RLAST` on
the last. That is expressed entirely in the **driver seam**: the response item already carries
`arlen`, so the driver loops the extra beats (data from an `araddr + i` memory model, `RLAST` on
the final beat). No framework change again — the second epic slice, like the first, is a pure
example. [`axi_read_burst`](../examples/axi_read_burst/) issues bursts of 1/4/2/3 beats and checks
per beat (id, data, `RLAST` framing); mutation-proved three ways (too few beats → stranded; wrong
`RLAST` → framing error; wrong data → mismatch). It keeps one read outstanding at a time to
isolate the burst axis from out-of-order — their **interleaving** (R beats of different ids
intermixed) is deferred to slice 5.

Adversarial review earned one fix here: the burst checks first lived only in the DUT `$error`,
which the **UVM-severity-based** regression verdict cannot see — so `make regress` reported PASS
on a broken burst. The fix is a **UVM burst oracle in the monitor**: it re-derives the expected
`R`-beat sequence from the observed `AR` and raises `uvm_error` on a wrong beat/`RLAST`/count (a
`check_phase` catches a stranded burst that end-of-test detection would otherwise miss). Now each
mutation flips the automated verdict to FAIL. The recurring lesson: a passing test is only proof
if the thing that would fail is visible to the *automated gate*, not just to a human reading the
log.

## The ready handshake (slice 3) — the first framework feature, closing the T6 gap

Slices 1–2 were pure examples; slice 3 is the first that needed the **generic framework** to
change — and it closes the one concrete gap the whole T6/AXI campaign named. Real AXI holds
`valid` until `ready` and issues requests **back-to-back**, so the monitor's edge-detect
under-counts (it sees only the first of a held-valid burst). The opt-in **`request_ready:`**
feature switches the monitor to a **level capture** (`valid && ready`, one publish per accepted
cycle); byte-identical when absent. [`axi_handshake`](../examples/axi_handshake/) drives 4
back-to-back requests plus `rready` response backpressure, mutation-proved via a UVM oracle that
counts AR vs R transfers (revert to edge-detect → the four collapse to one → `UVM_ERROR`). Two
seams carry the protocol: co-sampling the qualifiers at one edge (the clocking-block split means
a driven signal is sampled a cycle early), and the driver holding `rvalid` until `rready`.

## The full slave (slice 4) — the decomposition was the answer

The "deep gap" — a *unified* multi-channel agent sampling two request streams (`AR`+`AW`) — turned
out to be a **non-gap**: a full AXI slave is the **composition** of the read agent (slice 0) and
the write agent (slice 1) as two independent responders on one DUT, which is the decomposition T6
named. [`axi_slave`](../examples/axi_slave/) is exactly that, and it is a **pure example** — the
YAML is two agent stanzas, QuickUVM auto-wires both interfaces (`rd_if`→AR/R, `wr_if`→AW/W/B) to
the one DUT with no `tb_top` glue, and each agent reuses its slice's seams unchanged. Both channels
run green concurrently (reads 3/3 + writes 3/3, a cross-id reorder on each), and the capstone claim
— **independence** — is mutation-proved on the automated verdict: break one channel and only that
channel's UVM oracle fails, the other stays green. (Adversarial review caught the first cut leaning
on DUT `$error` for correctness, invisible to the UVM-severity gate — the recurring silent-pass;
fixed with a per-channel monitor oracle that makes id-correctness, `SLVERR`, and the reorder
verdict-carrying.) So the decision the epic deferred ("first-class unified agent vs two agents
sharing a bus") resolves in favour of **two agents**: it needs no new shape, and the two-agent form
is the honest AXI structure anyway (five independent channels, two transaction types).

## Where the real framework gap still is (slice 5)

Slice 1 moved the boundary, it did not erase it. The genuine open questions:

- **Slice 3 — the ready handshake.** `axi_read`/`axi_write` are valid-only: the master pulses
  `xVALID` and the slave never backpressures with `xREADY`. Real AXI is a two-sided
  valid/ready handshake per channel, and the qualifier is **edge-detected** — a `VALID` held
  high across several `READY` accepts is under-counted (T6 §4). Precise handshake accounting
  is the first thing that may need more than a seam.
- **Slice 4 — one unified `axi` agent.** A real AXI agent carries *all five* channels and both
  transaction types. That genuinely is two request streams (`AR` **and** `AW`) monitored by one
  agent — the T6 limit, un-refined, because here you cannot collapse them (they are different
  transactions, not two halves of one). This is the deep gap: either a monitor that publishes to
  two request paths, or the honest answer that AXI is **two agents** (read + write) sharing an
  interface.
- **Slice 5 — full VIP.** Two agents + exclusive-access/atomic glue + a memory model =
  protocol-VIP effort. Out of QuickUVM's generic single-block scope by design; the value of the
  epic is proving how *far* the generic machinery reaches before that line.

## Verdict

Slices 0–4 are **done and green**: out-of-order responses (0), the AW+W coupling (1), bursts (2),
and the full-slave composition (4) as pure examples, plus the valid/ready handshake (3) as the
epic's one framework feature — the concrete T6 gap, closed. The architectural question the epic
deferred — unified multi-channel agent vs two agents on a bus — is **answered**: the full slave is
a composition of two independent agents (slice 4), needing no new shape. So of the whole epic, the
generic machinery covered every slice with only **one** targeted feature (`request_ready:`); the
rest is examples + seams. What remains (slice 5 — burst×OoO beat interleaving, exclusive/atomic
access) is protocol depth that lives in seams, out of QuickUVM's generic single-block scope by
design — the honest boundary the campaign set out to find, now drawn by construction.
