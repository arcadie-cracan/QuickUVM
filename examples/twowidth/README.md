# twowidth — one VIP, two widths, one bench (C3 multi-instantiation)

The C3 **Accept** example: a single parameterized agent VIP instantiated **twice
at different widths** in one testbench. It builds on [pwidth](../pwidth) (the
`#(W)`-parameterized VIP) — here the same VIP also declares `instances:`.

## `instances:`
```yaml
agents:
  - name: io
    parameters:
      - {name: W, default: 8}
    instances:
      - {name: io8,  values: {W: 8}}
      - {name: io16, values: {W: 16}}
    ports:
      inputs:  [{name: din,  width_param: W}]
      outputs: [{name: dout, width_param: W}]
```
QuickUVM generates the VIP class set **once** (`io_agent#(W)`, `io_seq_item#(W)`,
`io_driver#(W)`, …) and then, for each instance, wires up a full independent
datapath at that instance's width:

- **two interfaces** — `io_if#(8) io8_if_inst`, `io_if#(16) io16_if_inst`;
- **two DUTs** — `twowidth#(8) io8_dut`, `twowidth#(16) io16_dut`;
- **two agents** — `io_agent#(8) io8_agnt`, `io_agent#(16) io16_agnt`, each fed
  its own virtual interface (distinct config-db keys `io8_vif` / `io16_vif`);
- **two scoreboards** — a concrete `twowidth_io8_scoreboard` typed on
  `io_seq_item#(8)` and `twowidth_io16_scoreboard` on `io_seq_item#(16)`, each
  with its own `predict()` (`dout = din + 1` at that width);
- a test that forks **one sequence per instance**, one on each sequencer.

An agent with **no** `instances` keeps the single-instantiation wiring and is
byte-identical to before — entirely opt-in.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
Both instances pass **51/51 on Xcelium** (0 errors, 0 fatals) — the 8-bit and the
16-bit datapath are checked simultaneously by their own scoreboards, from one
reused VIP.

## Why a concrete scoreboard per instance
The VIP classes are parameterized and reused; the scoreboard trio
(predictor/comparator/reference model) is generated **concrete** per instance
(`twowidth_io8_*`, `twowidth_io16_*`) rather than as a parameterized class. This
is deliberate: a parameterized predictor cannot keep its `predict()` body in a
separate `reference_model.svh` file, because SystemVerilog forbids an
out-of-block method definition using class-specialization syntax
(`function … io_predictor#(W)::predict(…)`) — Xcelium rejects it. Keeping each
instance's predictor concrete preserves the "one file you edit is the reference
model" workflow while still giving each width its own checker.
