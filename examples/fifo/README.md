# fifo — multi-agent example (C2: virtual sequencer + virtual sequences)

A synchronous FIFO with **two interfaces** — a write port (`wr_en`/`wr_data`,
sees `full`) and a read port (`rd_en`, sees `rd_data`/`empty`). It is QuickUVM's
first multi-agent bench and the worked example for **C2**: a virtual sequencer
(`fifo_virtual_sequencer`) and virtual sequences that coordinate the two agents.

## What C2 generates
- `fifo_virtual_sequencer.svh` — a virtual sequencer holding `wr_sqr`/`rd_sqr` handles (wired in
  the env's `connect_phase`).
- `fifo_base_vseq.svh` — `` `uvm_declare_p_sequencer(fifo_virtual_sequencer) `` so virtual
  sequences reach each agent's sequencer via `p_sequencer.<agent>_sqr`.
- `smoke_vseq.svh` (**sequential**) and `stress_vseq.svh` (**parallel**, `fork…join`).
- The `smoke`/`stress` tests start their vseq on `e.vsqr`.

## Stimulus (S2 library)
- `wr_push` — `incrementing` `wr_data` (0..15) with `wr_en=1`; `wr_rand` — random.
- `rd_pop` — `rd_en=1` for deterministic drains; `rd_rand` — random.

## Checking (two-stream, by hand)
The default scoreboard is single-stream, so the FIFO is checked by a **two-stream**
model wired in pragmas: one `uvm_tlm_analysis_fifo` per agent (env), drained by the
test. A few DUT-specific choices make this robust with the generated registered
monitor:
- **Registered read**: `rd_data` is flopped, valid the cycle after `rd_en` — which
  matches the monitor pairing `rd_en`@N with `rd_data`@N+1.
- The drivers **deassert `wr_en`/`rd_en` when idle** (a one-line `drive_item`
  pragma), so a finished sequence leaves the FIFO alone.
- `smoke_vseq` writes all 16, **then** reads — writes and reads are temporally
  separated, so the read stream must come back in order (`k`-th read == `k`).

`stress_vseq` interleaves writes and reads per cycle; a strict in-order check there
needs a cycle-aligned multi-stream scoreboard (roadmap **A2**), so it runs as a
soak (completes, no `rd_data` X while non-empty).

## Layout
- `rtl/fifo.sv` — clean MIT synchronous FIFO (registered read).
- `fifo.yaml` — config: `external_reset`, two agents, S2 libraries, `virtual_sequences`.
- `gen/` — generated TB; hand-filled pragmas: the two driver idle-deasserts, the
  `wr_push`/`rd_pop` enable constraints, the env analysis-fifo wiring, and the
  per-test check.
- `sim/xrun.f` — Xcelium filelist (wires the real `rtl/fifo.sv`).

## Run
```bash
quick-uvm generate -c fifo.yaml -o gen
cd sim
xrun -f xrun.f +UVM_TESTNAME=smoke    # -> *** FIFO DATA INTEGRITY PASS *** (16/16, 0 errors)
xrun -f xrun.f +UVM_TESTNAME=stress   # -> concurrent soak, 0 errors
```
