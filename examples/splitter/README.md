# splitter — multi-transaction-type scoreboard (A2)

One request stream, a DUT with **two different-typed output channels**, and **one
typed scoreboard per channel**. This is the worked example for the multi-transaction-
type strand of **A2** — it finalizes the scoreboard / comparison-strategy library.

## The DUT
[`rtl/splitter.sv`](rtl/splitter.sv) takes a valid-qualified request `{req_id,
req_data}` and produces, on its own latency, a response on **both** channels carrying
the same tag:
- **channel A (sum):** `a_sum = req_data + req_id` — an 8-bit payload (latency 2);
- **channel B (flag):** `b_flag = (req_data >= 0x80)` — a 1-bit payload (latency 3).

The two channels are **different transaction types** (`cha_seq_item` vs `chb_seq_item`,
distinct fields), so a single shared scoreboard can't check both.

## Two typed scoreboards
`splitter.yaml` declares two two-stream scoreboards, one per channel:
```yaml
analysis:
  scoreboards:
    - {name: sum_sb,  source: req, monitor: cha}
    - {name: flag_sb, source: req, monitor: chb}
```
Because there are **≥2** scoreboards, QuickUVM generates a **separate typed set per
scoreboard** — `splitter_sum_sb_{predictor,comparator,scoreboard,reference_model}` and
`splitter_flag_sb_{…}` — each typed to its own `predict(req) → channel` pair. With a
single scoreboard the generator keeps the shared `<dut>_*` set (byte-identical), so
this multi-set naming kicks in only when you actually need ≥2.

Each channel is its own in-order pipeline, so both scoreboards use the default
in-order matching; `emit_when` keeps idle / pipeline-fill cycles out so each channel's
i-th response lines up with the i-th request.

## Layout
- `rtl/splitter.sv` — the two-channel DUT (`gen/splitter.sv` is the generated stub).
- `splitter.yaml` — three agents (`req` active, `cha`/`chb` passive) + the two
  per-channel scoreboards.
- `gen/` — generated TB; the user-filled pragmas are the two `prediction_logic`
  bodies (`splitter_sum_sb_reference_model.svh` → `a_sum`, `splitter_flag_sb_reference_model.svh`
  → `b_flag`), the `req_driver` pacing, and the `rand_test` drain.
- `sim/xrun.f` — Xcelium filelist (`rtl/splitter.sv` as the DUT).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
Both scoreboards match **30/30 on Xcelium, 0 errors**. Breaking one channel's golden
model (e.g. drop the `+ req_id` in the sum model) fails **only** that scoreboard
(27/30) while the other stays 30/30 — the two typed scoreboards check independently.
