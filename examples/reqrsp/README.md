# reqrsp — two-stream out-of-order scoreboard (A2)

A tagged request/response unit whose responses are **reordered** relative to the
requests, checked by a two-stream scoreboard that matches each response to its
predicted expected **by tag**. This is the worked example for **A2** (scoreboard /
comparison-strategy library) and meets its Accept bar: *an out-of-order scoreboard
matches a reordering DUT model.*

## The DUT — two latency lanes
[`rtl/reqrsp.sv`](rtl/reqrsp.sv) routes each valid request by `req_id[0]` to one of
two lanes — even ids to lane 0 (latency 2), odd ids to lane 1 (latency 5). A response
from the fast lane therefore **overtakes** an earlier response from the slow lane, so
the response stream is reordered vs the request stream. Each response carries its
request's tag and `rsp_data = req_data + req_id`.

*No-collision invariant:* with the two lane latencies differing by an **odd** number
and requests **paced one every two cycles** (the req driver does this), the two lanes
can never complete on the same cycle, so the output is a simple OR-mux — no arbiter.
An `assert property` guards the invariant.

## Two streams, matched by tag
`reqrsp.yaml` wires a single two-stream scoreboard and selects out-of-order matching:
```yaml
analysis:
  scoreboards:
    - name: sbd
      source: req           # request stream → predictor
      monitor: rsp          # response stream → comparator "actual"
      match: out_of_order
      match_key: rsp_id      # the tag both expected and actual carry
```
The comparator pools each predicted expected response by `rsp_id` (a **queue per key**,
request-order within a key) and matches each observed response to its key's queue
front. A response with no pending request is an error; expected never matched at the
end raises `SB_LEFTOVER`. Queue-per-key is robust to tag reuse — a reused tag goes to
the same lane, so it stays in order within its key. The predictor is **stateless**
(`predict(req)` just maps `req_data + req_id`); `emit_when:` keeps idle / pipeline-fill
cycles out of the scoreboard.

## Layout
- `rtl/reqrsp.sv` — the two-lane DUT (`gen/reqrsp.sv` is the generated stub, unused).
- `reqrsp.yaml` — two agents (`req` active / `rsp` passive), each with `emit_when`,
  plus the out-of-order two-stream scoreboard.
- `gen/` — generated TB; the user-filled pragmas are:
  - `reqrsp_reference_model.svh` `prediction_logic` — the stateless `predict(req)→rsp`.
  - `req_driver.svh` `drive_item_additional` — one valid pulse per request (the
    every-two-cycles pacing the no-collision invariant relies on).
  - `rand_test.svh` `run_phase_additional` — a drain so the last in-flight responses
    are matched before the test ends.
- `sim/xrun.f` — Xcelium filelist (`rtl/reqrsp.sv` as the DUT).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
**Out-of-order matches 30/30 on Xcelium, 0 errors.** Flipping the scoreboard to
`match: in_order` on the same DUT fails 18/30 — the responses really are reordered, and
keyed matching is what fixes it. Removing the test's drain trips the `SB_LEFTOVER` net.
