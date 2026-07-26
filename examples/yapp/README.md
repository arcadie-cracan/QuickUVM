# yapp — packet router (one agent observes the whole interface; single-stream scoreboard)

A small **YAPP-style packet router**: one input channel routes each valid packet to
one of three output channels by its 2-bit destination address, with a one-cycle
registered latency. Address `3` means **drop** — no output that cycle. It is the
classic teaching DUT — small enough to hold in your head, rich enough to need a real
scoreboard — and it is the backing bench for the **QuickUVM Architect** visual
tutorial (`QuickUVM-Architect/docs/tutorial-yapp-router.html`).

## The DUT
`rtl/yapp_router.sv`: inputs `in_valid`, `in_addr[1:0]`, `in_data[7:0]`; three output
channels `out{0,1,2}_valid` / `out{0,1,2}_data[7:0]`. On a valid packet the payload
appears **one cycle later** on `out<addr>` (`out<addr>_valid` high); `in_addr == 3`
routes nowhere. Registered (`posedge clk`, async `rst_n`).

## One agent, not four
A router invites a "one input agent + three output agents" instinct. Here a **single
`pkt` agent drives the input and observes all three outputs**, so the scoreboard
predicts the entire output vector from one input packet in a single self-consistent
transaction — no cross-agent ordering to reconcile. (Independent per-channel
handshakes are where you would reach for separate output agents.)

## Black-box destination enum
`in_addr` carries an `enum:` in `yapp.yaml` (`P0=0, P1=1, P2=2, DROP=3`), so QuickUVM
generates a **TB-owned** `in_addr_e` — the destinations read by name, randomization
self-constrains to the four legal values, and the golden model routes by `P0/P1/P2`
rather than magic numbers. The type is the testbench's own (declared from the spec),
never imported from the DUT — the black-box discipline: a wrong DUT encoding is
*caught*, not mirrored.

## Single-stream scoreboard (A2) + the golden model (K0)
`analysis.scoreboards: [{name: sbd, source: pkt}]` is a **single-stream** scoreboard:
it predicts the outputs from the sampled inputs and compares them against what the DUT
produced, all in one transaction — there is no separate monitor agent because this one
agent already sees inputs and outputs together. The whole check is six lines of
`prediction_logic` in `gen/yapp_router_reference_model.svh`:

```systemverilog
extr.out0_valid = (t.in_addr == P0);
extr.out1_valid = (t.in_addr == P1);
extr.out2_valid = (t.in_addr == P2);
extr.out0_data  = t.in_data; extr.out1_data = t.in_data; extr.out2_data = t.in_data;
```

`emit_when: in_valid` scores only cycles that actually carry a packet; the sequence
constrains `in_valid == 1` so every generated item is a real packet.

## Functional coverage (V1)
`analysis.coverage` puts a coverpoint on `in_addr`; being an enum field it auto-bins
one bin per destination, so closure means "we exercised P0, P1, P2 **and** DROP".

## Layout
- `rtl/yapp_router.sv` — the registered packet-router DUT (MIT).
- `yapp.yaml` — config: the `pkt` agent (inputs + six observed outputs, the `in_addr`
  enum, `emit_when` / constraint), the `sbd` scoreboard and the `in_addr` coverpoint.
- `gen/` — the generated testbench; the only hand-written code is the six-line
  `prediction_logic` seam in `yapp_router_reference_model.svh`.
- `sim/xrun.f` — Xcelium filelist.

## Run
```bash
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test     # -> TEST PASSED, 49/49
```

Green on Cadence Xcelium **and** Siemens Questa (49/49, 0 UVM_ERROR). To reproduce the
generated tree:

```bash
quick-uvm generate -c yapp.yaml -o gen
```
