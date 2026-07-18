# Composing `count` + the hybrid agent — the alert_handler alert-sender array

The [alert_handler probe](alert_handler_assessment.md) named three [I] gaps, each now a shipped
feature: I-7 the [hybrid agent](hybrid_agent_assessment.md), I-8 the
[windowed scoreboard](parity_roadmap.md), I-9 [`count`](count_array_assessment.md). `count` was
scoped to *initiator* agents; both features named the same follow-up — **compose them** into N
hybrid alert-senders on one DUT. This does that (`examples/alert_array`).

## The composition

`count` gave the shared-vectored-DUT wiring; the hybrid agent gave a responder that also initiates
with an un-maskable request-drain liveness. Composed: **`count` + `proactive: true`** — N replicas,
each a full hybrid, into one vectored DUT.

- The `count` validator, previously rejecting all responders, now allows a **proactive** responder
  (the hybrid); a *pure* responder is still rejected.
- Each replica forks its **own** responder sequence (answering its channel's ping) and runs its
  **own** proactive sequence (raising its channel's alerts) on its **own** sequencer — UVM arbitrates
  the two, as in the standalone hybrid.
- Each replica's sequencer carries its **own** request-FIFO-drain liveness. This is the load-bearing
  point: the N liveness checks are independent, so a dead responder in one channel is caught on its
  own, not masked by (nor masking) the proactive alert traffic on the others.

## Proof

3 hybrid alert-senders, one vectored DUT: 3×499/499 on Xcelium, `make regress` 2/2. Two
mutations, each showing per-replica independence (`MUTATIONS.md`):

- corrupt **only channel 1**'s alert latch → **only `sndr_1`'s scoreboard fails**;
- hang **only replica 1's** responder → **only `sndr_1_agnt.sqr`'s DEAD_RESPONDER fires** (123
  unanswered pings), the others drain clean.

That the responders keep up at all — under back-to-back proactive alerts on the same sequencer, for
all three replicas at once — is the non-trivial part, and it holds (UVM arbitration + an end-of-test
drain).

## What it means for alert_handler

The probe's "hard break at the mapping stage" is now: three primitives shipped, and the two
structural ones **compose** into the actual alert-sender array. A *complete* alert_handler bench
still needs protocol depth — the differential-pair / four-phase / ping handshake in the driver seam,
the escalation timers as windowed checks, the ~7 local alerts — but that is seam-filling on an
existing shape, not a missing primitive. The generator now carries the topology; the protocol is the
user's to write, as it is under any methodology.
