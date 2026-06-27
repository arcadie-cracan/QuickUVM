# reqrsp — two-stream in-order scoreboard (A2, slice 1)

A tagged request/response unit checked by a **two-stream** scoreboard: one agent
drives the request stream, a second agent monitors the response stream, and the
scoreboard predicts each expected response from the observed request. This is the
worked example for **A2** (scoreboard / comparison-strategy library) — the
generalized version of the two-stream check the [fifo example](../fifo/) used to
hand-wire.

## The DUT
[`rtl/reqrsp.sv`](rtl/reqrsp.sv) is a single in-order lane: a valid-qualified
request `{req_id, req_data}` enters and, `LAT` cycles later, the matching response
`{rsp_id = req_id, rsp_data = req_data + req_id}` leaves — same tag, in request
order. (The A2 out-of-order slice adds a second lane with a different latency so
responses can overtake and must be matched by tag.)

## Two streams, one scoreboard
`reqrsp.yaml` declares two agents and wires them with `analysis.scoreboards`:
```yaml
analysis:
  scoreboards:
    - name: sbd
      source: req      # input/stimulus stream → predictor
      monitor: rsp      # output/response stream → comparator "actual"
```
The generator types the seam as `predict(req_seq_item) → rsp_seq_item`: the
predictor consumes the **req** stream and emits the expected response; the
comparator matches it, in order, against the observed **rsp** stream. The
`req` agent is active (drives); `rsp` is a passive monitor.

## `emit_when` — aligning the streams
Both agents set `emit_when:` (`req_valid` / `rsp_valid`), so the monitor publishes a
transaction only when its valid signal is high. That keeps idle and pipeline-fill
cycles out of the scoreboard, so the i-th valid request lines up with the i-th valid
response and the in-order FIFO match needs no cycle-counting — the pipeline latency
is absorbed by the valid qualification. The golden model is therefore **stateless**:
`predict(req)` just maps `req_data + req_id` onto the expected response.

## Layout
- `rtl/reqrsp.sv` — the DUT (`gen/reqrsp.sv` is the generated stub, unused by the sim).
- `reqrsp.yaml` — two agents (`req` active / `rsp` passive), each with `emit_when`,
  plus the `analysis` two-stream scoreboard.
- `gen/` — generated TB; the user-filled pragmas are:
  - `reqrsp_reference_model.svh` `prediction_logic` — the stateless `predict(req)→rsp`.
  - `req_driver.svh` `drive_item_additional` — one valid pulse per request (paced).
  - `rand_test.svh` `run_phase_additional` — a drain so the last in-flight responses
    are compared before the test ends.
- `sim/xrun.f` — Xcelium filelist (`rtl/reqrsp.sv` as the DUT).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
GREEN on Xcelium: **30/30 vectors, 0 UVM_ERROR**. Mutating the golden model (drop the
`+ req_id`) makes the scoreboard report 27/30 failures — the two-stream check is real,
not a vacuous echo.
