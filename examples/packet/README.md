# packet — variable-length payload + constraints (S1)

The worked example for **S1 rich stimulus**: a packet-style transaction with a
**variable-length payload** and **transaction-level constraints**. A combinational
checksum DUT (`pkt_sum`) sums the first `len` bytes of a payload presented packed on
a wide `data` bus — one packet per vector, so the bench stays single-cycle.

## What S1 adds

- **`fields:`** — transaction-only data that is *not* an interface wire. Here
  `payload` is a `rand byte payload[]` (a dynamic array). QuickUVM generates the
  declaration, `uvm_field_array_int` automation, a sane size bound, and a `%p` print;
  the **bus (de)serialization stays user pragma code** ("skeleton, not magic") — in
  this example a 3-line `post_randomize()` packs `payload` into `data`.
- **`constraints:`** — a transaction-level list of raw SystemVerilog. This example uses
  both an **inter-field relation** (`len == payload.size()`) and a **`dist`** that
  weights short packets 3:1 (`payload.size() dist { [1:4] := 3, [5:16] := 1 }`).

The generated `trans_c` constraint block also carries an auto size-bound
(`payload.size() inside {[min_size:max_size]}`) so an unconstrained `rand` array can't
randomize to a runaway size.

## Layout

- `rtl/pkt_sum.sv` — combinational checksum DUT (sums the first `len` of up to 16 bytes).
- `packet.yaml` — config: `dut.combinational: true`, one `stream` agent with the
  `payload` field + the two constraints.
- `gen/` — generated TB. The only hand-filled pragmas are `post_randomize()` (packs
  `payload` → `data`, in `stream_seq_item.svh`) and the reference checksum (in
  `pkt_sum_reference_model.svh`).
- `sim/xrun.f` — Xcelium filelist.

## Run

```bash
quick-uvm generate -c packet.yaml -o gen
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test   # -> TEST PASSED, 61/61
```

The payload length varies across `[1:16]` with the `dist` bias toward short packets,
and `len == payload.size()` holds on every randomized transaction.
