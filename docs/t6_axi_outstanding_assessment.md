# T6 — AXI multi-outstanding, out-of-order responder — the campaign's first real gap

> **STATUS: CLOSED.** The gap this document found is now closed by `respond: pipelined` +
> `reorder_by:`, built and mutation-proved on Xcelium in `examples/axi_read/` (issue `[4 3 2 1 0]`
> → recv `[4 0 1 2 3]`, 5/5 answered, cross-id reorders=4; break the drain and the new
> `STRANDED_REQUESTS` check fires). See §7. The finding below is preserved as the record of the
> gap and the reasoning that settled it.

The question the campaign deferred twice — at T3 (tl_agent) and T5 (Ibex) — is whether a QuickUVM
responder can hold **N outstanding** requests and answer them **out of order by ID**, the way
PULP's `axi_rand_slave` (in `pulp-platform/axi`'s `axi_test.sv`) does. T6 answers it, **by running
it on Xcelium** rather than by inspection.

**Verdict (at the time of the finding): no. This was the first genuine capability gap of the
campaign** — and, unlike the five "it breaks" predictions that *didn't*, this one was **claimed to
work and doesn't**. Claims tagged **[C]** run-verified this session / **[I]** inspection /
**[P]** predicted.

---

## 1. What actually happens (run-verified)

A minimal spike (`docs/t6_axi_probe/`): a stub AXI-read **master** DUT issues 3 read requests with
IDs `{2,0,1}` and expects 3 R beats, matched by `rid`, in any order. The TB is a QuickUVM
`mode: responder` (`respond: on_request`) agent whose seams hold the per-ID reorder engine.

- **[C] Buffering works — for free.** The responder sequencer's `request_fifo` is a
  `uvm_tlm_analysis_fifo` (unbounded). With the responder made to hold, the run shows
  `DRIVE rsp ... (outstanding=2)` — requests N+1, N+2 genuinely accumulate while N is unanswered.
  Multi-outstanding *buffering* is not the gap.
- **[C] But the response path strands them.** The generated responder loop is
  `forever { get(req); <seam>; start_item(rsp); finish_item(rsp); }` — **one response per
  incoming request**, and the `get`/`start_item`/`finish_item` are **generated, not pragma**
  (`agent_responder_seq.svh.j2:69,84,85`). The seam can reorder *which* buffered request a given
  response answers, but it drives **exactly one** response per `get`. After draining a burst into
  per-ID queues and answering one, the loop returns to `get()` and **blocks forever** on a *new*
  request that never comes — the rest of the burst is stranded. The run proves it: 3 requests in,
  `outstanding=2` held, **1 response driven**, 2 stranded.

There is no `respond: pipelined` shape (`models.py:749` — only `on_request`/`prefetch`/
`combinational`), and no `outstanding:`/`reorder_by:` knob. The loop that would answer the queue
without blocking on `get` cannot be written in a seam.

---

## 2. The claim that was wrong — and why running it mattered

A scoping pass concluded this capability was **expressible today [C]**, "proven by construction":
it generated the responder, filled the two seams with a per-ID queue + `try_get` drain +
`pick_ready_id()` reorder engine, and confirmed **regeneration survives** (`0 updated`, all markers
preserved). All of that is true — **and none of it is proof the responder works**. It is exactly
the failure the T2 review named: a paper claim that *reads fine* and *regenerates cleanly* but was
**never simulated**. Running it shows the strand in §1; a "seam-abuse" variant that hand-calls
`start_item`/`finish_item` for the whole queue was also tried and produced **pairing bugs, not
clean OoO** — so even fighting the loop does not cleanly express it.

This is the same discipline that refuted five *over-pessimistic* "it breaks" predictions (K0 ×2,
CPOL=1, the T4 schema gaps, the T5 chandle), turned on an *over-optimistic* one. **Reasoning and
generation-checking are not enough in either direction; only the simulation settles it.**

---

## 3. The feature it needs (the T5-scoped `respond: pipelined`)

The fix is the responder shape T5 already scoped, refined against the run:

    respond: pipelined
    reorder_by: arid        # the ID field on the sequence_item -> per-ID queues, same-ID in order
    max_outstanding: 0      # 0 = unbounded (match axi_rand_slave); N = credit-limited

What it must emit as **scaffold** (not seam), because the run shows the seam can't:

- A loop that **answers from a per-ID queue without blocking on `get`** — an independent accept
  thread (fed by the monitor) fills the queues; a separate drive thread empties them. This is
  exactly `axi_rand_slave`'s `fork … handle_read(id) … join_none` structure, one process per ID.
- Same-ID responses in order (`pop_front`), cross-ID free to reorder — the AXI ordering rule.
- A driver that can drive **multiple responses** on the response channel, not one-per-`get_next_item`.

Honest sizing: this is a real responder-shape feature (~a slice), not a seam fill. Not built here —
banked as a finding, like T3/T5.

---

## 4. The boundary: the OoO responder axis vs the full AXI VIP

Even with `respond: pipelined`, a *faithful* `axi_rand_slave` is a **larger, gap-by-design** thing,
and the reasons are structural [I]:

- **Two independent request streams (AR + AW).** `_check_responder` allows exactly one 1-bit
  `request_valid` and the monitor writes one `request_ap` (`agent_monitor.svh.j2:59`, outside any
  pragma). One agent samples one request stream.
- **Two concurrently-driven response streams (R + B).** The `on_request` driver is serial (no fork);
  only the *continuous* shape exposes a `driver_threads` fork, and the two shapes don't compose.
- **Handshake accounting.** The qualifier is **edge-detected**, so a real AXI `arvalid` held high
  across multiple `arready` accepts is under-counted — the spike had to *pulse* `arvalid` to make
  each request a distinct edge. Precise AXI handshake counting isn't expressible via the qualifier.

AXI decomposes cleanly into a **read agent** (AR→R, OoO by ID — the `respond: pipelined` case) and a
**write agent** (AW,W→B, in order — `axi_rand_slave` doesn't cross-ID-reorder writes). A full VIP is
a two-agent build with cross-agent glue for atomics — a protocol-VIP effort, out of scope by design.
**The genuine capability question is the OoO responder; that is the gap, and it is real.**

---

## 5. Not a metric comparison

`axi_rand_slave` is **plain SystemVerilog classes** — hand-written `forever` processes forked in
`run()`, member queues, no `uvm_component`/`uvm_sequence`/factory. There is no generator on the other
side and no hand-written-UVM baseline. So T6 is a **capability probe**, not a generator-vs-generator
metric like T4 — and no line-count is reported, deliberately.

---

## 6. Honest limits

- The strand is **[C]** (run-verified, responder-side: `outstanding=2`, one response driven). The
  master-side capture in the spike has a driver-output-skew/held-`rvalid` timing bug (`recv=2,2,2`)
  that is orthogonal to the strand and not cleaned up — the responder-side evidence is the proof.
- **`respond: pipelined` is not built** — §3 is a scoped design, tagged [P] for the parts not
  generated. This is a banked finding.
- Only the **read (AR→R) channel-pair** was probed; the write path and the full 5-channel VIP are
  §4's gap-by-design, not exercised.

---

## 7. Resolution — `respond: pipelined` (built + mutation-proved)

The scoped feature of §3 is now built. It is a new responder *shape*, opt-in and byte-identical for
every existing bench:

    respond: pipelined
    reorder_by: arid     # the sampled request-ID field the per-queue buckets key on

**What it emits as scaffold** (the parts §1 proved the seam could not express):

- The responder sequence forks **two threads** — an ACCEPT thread that drains `request_fifo` into
  per-ID queues (`id_q[int][$]`), and a DRIVE thread that answers the backlog **without blocking on
  a new request**. This is exactly `axi_rand_slave`'s accept/serve split, and it is the loop the
  `on_request` shape could not write in a seam.
- Same-ID responses in arrival order (`pop_front`); cross-ID reordered by a deterministic
  lowest-ready-id-first policy (one line to change). The `response_logic` seam is unchanged from
  `on_request`, so flipping shapes preserves the user's fill.
- A new liveness guard, `STRANDED_REQUESTS`, on the sequencer: it fails if `accepted != answered`.
  `DEAD_RESPONDER` catches "answered nothing"; it is **blind to a strand** — the §1 failure, where
  the responder answers *some* of a burst. This check makes that failure impossible to ship silent.

**Run-verified [C]** (`examples/axi_read/`, Xcelium 25.09): the master floats five reads in
descending id order and the slave models a read latency, so a backlog builds and lowest-first drains
it ascending:

    [MASTER] issue order = [ 4 3 2 1 0 ]  recv order = [ 4 0 1 2 3 ]  got=5/5  cross-id reorders=4
    UVM_ERROR : 0   UVM_FATAL : 0

**Mutation-proved [C]** (`examples/axi_read/MUTATIONS.md`):

- Break the drain (drive thread answers once): `STRANDED_REQUESTS` — *accepted 5, answered 1* — a
  UVM_ERROR, exactly the §1 strand, now caught rather than passed. `got=1/5`.
- Flip the reorder policy to highest-first: `recv == issue`, reorders=0 — proving the baseline's
  reorder is produced by the policy, not by luck.

**Still gap-by-design** (unchanged from §4): the full 5-channel AXI VIP. `respond: pipelined` is the
read channel-pair (AR→R); AR+AW / R+B and atomics remain a two-agent protocol-VIP build. The
genuine *capability* question — the out-of-order responder — is what this closes.

**The meta-lesson, now with its bookend:** §2 recorded that a scoping pass called this "expressible,
proven by construction" from generation alone, and running it refuted that. The fix earns the mirror
rule: it was built by **running every claim** — the strand, the reorder, and the liveness teeth were
each proven by a mutation that made the bench fail, not by reading the generated code.
