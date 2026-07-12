# memslave — the reactive / responder (device) agent

**The DUT is the bus master. The testbench is the memory device.** Nothing in the TB
initiates: the agent waits for the DUT's request and drives a computed response.

This is the **continuous** responder shape. `gnt` is a per-cycle obligation — the DUT
samples it every cycle — so a driver that parked between items would leave it stale and the
DUT would hang. Declaring `idle:` is what selects that shape.

```yaml
agents:
  - name: mem
    mode: responder      # the DUT initiates; we answer
    request_valid: req   # a SAMPLED port: "the DUT issued a request"
    idle:                # PRESENCE => the continuous shape (non-blocking driver)
      gnt: 0
      rdata: 0
    ports:
      inputs:  [gnt, rdata]      # what we DRIVE  = the RESPONSE (the DUT's inputs)
      outputs: [req, addr, ...]  # what we SAMPLE = the REQUEST  (the DUT's outputs)
```

The port-direction model is **unchanged** — a device agent still drives the DUT's inputs and
samples its outputs. Only the *timing* is reactive.

## Where the reactivity lives (not in the driver)

```
DUT drives a request
  -> the MONITOR decodes it and writes it to `request_ap`
  -> the SEQUENCER's TLM FIFO buffers it
  -> the forever RESPONDER SEQUENCE's blocking get() unblocks
  -> it computes a response  <-- YOUR SEAM (`response_logic` pragma)
  -> start_item/finish_item hand it to the driver
  -> the driver drives the response pins
```

Keeping the decode in the **monitor** (which must already decode the protocol for passive
mode) is why the driver does not have to. See
[`docs/reactive_agent_investigation.md`](../../docs/reactive_agent_investigation.md).

The **agent owns its responder** and forks it in `run_phase` — not a phase
`default_sequence`, because a phase sequence is *killed* when its phase ends, and a
responder raises no objection (it is a service, not stimulus), so it would be torn down
instantly. This bit is easy to get wrong and it was: the first version generated exactly
that bug, and the bench "passed" while the device never answered.

## Run

```bash
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test   # -> TEST PASSED, 34/34
```

## The self-check, and why the first one was worthless

The scoreboard predicts `last_data` from the **request address**, using its own memory model —
**not** from the `rdata` it observed on the bus. That distinction is the whole point.

The first version derived the expected value from the observed `gnt`/`rdata`, which made it a
tautology with respect to the responder: it could only ever prove "the DUT registered whatever
appeared on the pins". An adversarial review demonstrated on Xcelium that with that check,

* a responder mutated to `gnt = 0` — **the device never answers, the DUT wedges, zero transfers
  complete** — still reported **TEST PASSED 34/34**, and
* a responder answering `rdata = DEADBEEF` (ignoring the address entirely) also **passed**.

Which is exactly the failure mode this whole feature exists to prevent. The mutation proof at
the time only broke the DUT's *capture register* — the one thing that check did cover.

It now catches all three:

| mutation | result |
|---|---|
| DUT captures wrongly (`last_data <= rdata + 1`) | **FAIL** 31/34 |
| responder answers wrong data (`rdata = DEADBEEF`) | **FAIL** 31/34 |
| responder never answers (`gnt = 0`) | **FAIL** — `DEAD_RESPONDER` + `NO_PROGRESS`, `make regress` exits nonzero |

The dead-responder case needs an **end-of-test** assertion, not a per-transaction compare: with
no grant the DUT never captures, so expected and actual are both zero and every comparison
agrees. `check_phase` asserts that grants happened and the DUT made progress.

Note the comparator still prints `TEST PASSED` in that case — it only counts its own vector
compares. The UVM severity block (`UVM_ERROR : 2`) is the truth, and that is what R1's
`make regress` parses. Never trust the banner.
