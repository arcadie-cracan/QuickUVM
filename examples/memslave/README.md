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

The scoreboard checks the real property: **whatever the reactive agent granted is exactly
what the DUT captured**. Breaking the DUT's capture (`last_data <= rdata + 1`) fails 31/34 —
the check is real.
