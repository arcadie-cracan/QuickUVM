# alert_array — composing `replicas` + the hybrid agent (the alert_handler topology)

**Can the two alert_handler features compose — N hybrid alert-senders into one DUT?** Yes. This
is the capstone: `replicas` (N replicas into one vectored DUT, I-9) + the hybrid agent
(`proactive: true`, I-7) together. Each of the N replicas **answers its own ping** (reactive) AND
**raises its own alerts** (proactive), and each gets **its own** request-FIFO-drain liveness — the
OpenTitan alert-sender array, built from generic primitives.

```yaml
agents:
  - name: sndr
    replicas: 3                # N replicas into one vectored DUT (I-9)
    mode: responder         # answer each channel's ping...
    request_valid: ping
    respond: on_request
    proactive: true         # ...AND raise each channel's alerts (I-7)
```

3 hybrid agents, one vectored DUT (`ping`/`resp`/`alert`/`adata`/`last_adata` all `[3-1:0]×w`),
3 per-channel scoreboards, 3 responder sequencers each with its own drain liveness. **3×499/499 on
Xcelium, 0 errors** (`make regress` 2/2). The responders keep up with the back-to-back proactive
alerts (UVM arbitrates the responder + proactive sequences on each replica's sequencer).

## Two proofs, both per-replica independent

[MUTATIONS.md](MUTATIONS.md):

- **Proactive path** — corrupt **only channel 1**'s alert latch → **only `sndr_1`'s scoreboard
  fails**; the other channels stay green.
- **Reactive liveness** — hang **only replica 1's** responder → **only `sndr_1_agnt.sqr`'s
  DEAD_RESPONDER fires** (123 unanswered pings); the others drain clean.

That second one is the point of the composition: each replica is a full hybrid with its **own**
un-maskable liveness, so a dead responder in one alert channel is caught independently of the other
N−1. Killing one does not mask, and is not masked by, the others.

By design the DUT does **not** consume `resp` (the ping response): a responder's liveness in QuickUVM
is the TB-side request-FIFO drain, not a DUT output — which is exactly why M2 catches a dead responder
whose DUT outputs are otherwise unchanged. Real alert_handler consumes the response into a
ping-timeout FSM; that (and the differential/four-phase handshake) is protocol depth for the driver
seam, not part of this composition proof.

## What this demonstrates

The [alert_handler probe](../../docs/alert_handler_assessment.md) predicted a "hard break at the
mapping stage." Its three [I] gaps became three features (hybrid, windowed scoreboard, count), and
this bench shows the two structural ones **compose** into the actual alert-sender array. What a
*complete* alert_handler bench still needs is protocol depth (the differential/ping handshake in the
driver seam, the escalation timers as windowed checks) — filling seams, not missing primitives.

## Run

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
# or the seed regression:
cd ../gen && make regress
```
