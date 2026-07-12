# memslave_zs — a responder for a DUT that will not wait

`memslave` and `memslave_zs` differ by **one line of YAML**:

    respond: combinational      # memslave_zs
    # respond: on_request       # memslave (the default)

and one line of RTL: the DUT no longer waits for `gnt`. It offers exactly one cycle, then
moves on and records a `missed`.

That one line is the whole point.

## The contract nobody wrote down

`mode: responder` had a hard timing contract that was never stated: **the response lands the
cycle AFTER the request is sampled.** It is structural, not a tunable — the response
round-trips

    monitor -> analysis fifo -> responder sequence -> sequencer -> driver -> cb1

and every pragma in that path runs *after* `get_next_item`. Nothing you can hand-write inside
the feature can answer sooner.

`memslave` never noticed, because its FSM parks in `REQ` and waits however long it takes. A
real serial device does not wait: full-duplex SPI drives MISO on the very edge it samples
MOSI. **Zero slack.**

`respond: combinational` says so. The response becomes a pure function evaluated in the
driver on the RAW request signals — no sequencer, no request fifo, no clocking block (`cb1`'s
output skew lands *after* the edge the DUT samples on, so a `cb1` drive is always exactly one
cycle late).

## The mutation — this example exists to fail

Flip the one line back to the default and regenerate:

    sed -i 's/respond: combinational/respond: on_request/' memslave_zs.yaml
    quick-uvm generate -c memslave_zs.yaml -o gen --allow-drop
    # move the memory model from mem_driver.svh's `response_logic` seam into
    # mem_responder_seq.svh's, then:
    make -C gen regress

| | result |
|---|---|
| `respond: combinational` | **TEST PASSED — 34/34**, `missed=0` |
| `respond: on_request` | **TEST FAILED — 35 UVM_ERROR**, `NO_PROGRESS`, `missed` climbing |

Note *which* check fires: **`NO_PROGRESS`, not `DEAD_RESPONDER`.** The responder is perfectly
alive — it grants every single request — it is just one cycle too late, so the DUT captures
nothing. A liveness check that only asked "did it respond?" would call that healthy.

(The regeneration needs `--allow-drop`: switching the contract moves the seam from the driver
to the sequence, and the merger refuses to drop hand-written code silently. That is the
preservation gate working, not a bug.)

## What is checked

The predictor derives expected `last_data` from the request **address**, through its own copy
of the memory model — never from the `rdata` observed on the bus. Deriving expected from the
observed value would be a tautology: it could never fail for a responder that answers the
wrong data, or too late. On top of that:

* **generated, in the driver** (`check_phase`, outside every pragma): `DEAD_RESPONDER` (drove
  zero responses) and `SILENT_RESPONDER` (drove only the idle value — an empty seam).
* **hand-written, in the predictor**: `DEAD_RESPONDER` (never granted) and `NO_PROGRESS` (the
  DUT completed zero transfers). A dead bench must not be able to end green through *any* path.

## Run

    make -C gen regress          # 1 test x 2 seeds, coverage merged
