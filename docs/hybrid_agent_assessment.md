# Hybrid (initiator + responder) agent — closing alert_handler gap I-7

The [alert_handler probe](alert_handler_assessment.md) named three [I] gaps. The cycle-accurate
reference model (I-8) is answered by the [windowed scoreboard](parity_roadmap.md). This closes the
second — **I-7, the hybrid alert-sender that has no first-class shape** — as a built, mutation-proved
feature (`examples/hybrid_alert`). The third (I-9, the ~63× agent array) stays open.

## The gap

An alert-sender does two unrelated things at once: it **answers the receiver's pings** (reactive)
and **spontaneously raises alerts** (proactive). QuickUVM's `mode` was `initiator` XOR `responder`,
and the reactive-agent work deliberately kept them apart: a responder's sequencer is *owned* by its
forever responder sequence, and `stimulus_agents` excludes responders so the test can never start a
second sequence there ("the random items would clobber the computed responses").

## The feature: `proactive: true`

Opt-in on an `on_request` responder. The agent stays a responder — the env still forks its responder
sequence — but it **also** joins the stimulus agents, so the test starts a proactive sequence on the
same sequencer and UVM arbitrates the two (the responder sequence blocks on the request FIFO; the
proactive one drives when it has an item). The `stimulus_agents` exclusion is relaxed *only* for a
hybrid, whose proactive items are meaningful, not garbage.

## The subtlety — and why the naive relaxation is wrong

Just relaxing the exclusion would ship a **latent false-green**. A responder's liveness is
`DEAD_RESPONDER` — the driver counts `m_responses` ("transfers I actually drove") and fails if it
stayed zero, because a dead responder is otherwise unprovable per-transaction. But a hybrid **also
drives proactive alerts**, which increment that same counter: a stone-dead ping-responder looks alive
because the alerts kept the driver busy.

So a proactive responder gets a different, **un-maskable** liveness — the **request-FIFO drain** on
its sequencer (`request_fifo.used() == 0` at end of test), the on_request analog of the pipelined
responder's `STRANDED_REQUESTS`. Proactive stimulus never touches the request FIFO; only the
responder sequence drains it. So an unanswered request always shows.

This is the interesting part of the build, and it is mutation-proved directly: killing the responder
while the alerts keep flowing (`examples/hybrid_alert/MUTATIONS.md`, mutation B) fails the test with
**129 unanswered pings** via the drain — while the comparator reports "TEST PASSED" *and* the
driver's `m_responses` check stays green (masked). Without the drain, that dead responder goes green.

## Status

- Built + Xcelium-green (`hybrid_alert` 620/620, `make regress` 2/2); both paths mutation-proved
  (proactive scoreboard; the anti-masking drain). Opt-in and byte-identical when `proactive: false`
  (all 43 examples regenerate unchanged); 6 unit tests; validation is fail-closed (proactive requires
  `mode: responder` + `respond: on_request`, and rejects `idle` — a continuous responder drives every
  cycle, leaving no room to interleave proactive stimulus).
- *One footgun, by design:* the drain check reads `request_fifo.used()` at **check_phase** (end of
  test), so the responder must have caught up by then. If the proactive sequence ends abruptly, give
  the responder a short drain (the demo's `hybrid_test` adds one in `run_phase_additional`) — else a
  late in-flight ping reads as a spurious "unanswered". Mid-run the FIFO transiently fills and drains;
  only the steady-state end matters.
- **alert_handler after this:** I-8 (cycle-accurate) → the windowed scoreboard; **I-7 (hybrid) →
  this**. Only **I-9** remains — one agent instantiated ~63× into one DUT (the reuse-array topology;
  C3 `instances` gives each its own DUT). That is the last of the three, and a separate build.
