# axi_slave — the AXI epic, slice 4 (capstone): the full AXI slave as two agents

A full AXI slave is **not a new agent shape** — it is the composition of a read channel
(`AR → R`) and a write channel (`AW + W → B`) as two **independent** responder agents on one
DUT. That is the decomposition [T6](../../docs/t6_axi_outstanding_assessment.md) named, and this
capstone proves it end-to-end. See [`docs/axi_epic_assessment.md`](../../docs/axi_epic_assessment.md).

## Two agents, one DUT — zero new machinery

Each agent reuses a prior slice **unchanged**:

| Agent | Channel | Reuses |
|---|---|---|
| `rd` | `AR → R`, out-of-order by `arid` | [`axi_read`](../axi_read/) |
| `wr` | `AW + W → B`, out-of-order by `awid` | [`axi_write`](../axi_write/) (the AW→W order-correlation) |

The YAML is just two agent stanzas. QuickUVM auto-wires both interfaces (`rd_if` → `AR/R`,
`wr_if` → `AW/W/B`) to the one DUT — no manual `tb_top` glue. The read agent's seams are
`axi_read`'s; the write agent's are `axi_write`'s (the awid queue popped on `WLAST`, the `wdata`
id-tag `SLVERR` order-check). Nothing about composing them needed a change.

## What runs

`rtl/axi_slave.sv` is an AXI master driving **both** channels: it floats 3 reads and 3 writes
with distinct descending ids, accepts `R` and `B` beats in whatever order the two slaves return
them, matches each by id, and checks each channel delivered all three with a cross-id reorder:

```
[SLAVE] reads got=3/3 reorders=2 | writes got=3/3 reorders=2
```

Green on Xcelium: `0 UVM_WARNING / 0 UVM_ERROR / 0 UVM_FATAL`. Deterministic across seeds.

## The verdict

Each agent carries its own verdict, exactly as its source slice does:

- **Delivery** (all `R`, all `B`) — the per-agent `STRANDED_REQUESTS` liveness (a genuine strand
  raises a `UVM_ERROR` from that agent's sequencer, verdict-visible).
- **Order / data** (reorder, the `SLVERR` mis-order check) — the DUT master's `$error`, the
  human-readable corroboration the read/write slices already use.

## Proved it can fail — per-channel independence

The capstone's claim is that the two channels are **independent**: a break in one fails only that
channel. Mutation-proved:

| Mutation | Effect |
|---|---|
| strand a read (skip `arid=2`) | reads `2/3` (fail) — **writes stay `3/3`** |
| break the write `AW→W` correlation | writes `SLVERR` + "not outstanding" (fail) — **reads stay `3/3`** |

Neither break leaks across the channel boundary. (Plus each agent's own mutation coverage, proved
in `axi_read` / `axi_write`.)

## Scope

The two channels are single-beat and out-of-order here (composing the slice-0/1 cores). Each can
independently carry bursts (slice 2) or the ready handshake (slice 3) — those are orthogonal per
channel; composing *all four* dimensions on one bench is more scaffolding than signal. The point
proved here is the **decomposition**: two agents, one bus, independent verdicts.

## Layout
- `rtl/axi_slave.sv` — the AXI read+write master DUT.
- `axi_slave.yaml` — two responder agents (`rd`, `wr`).
- `gen/` — user-filled seams are `axi_read`'s (rd) and `axi_write`'s (wr).
- `sim/xrun.f` — Xcelium filelist (both interfaces).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
