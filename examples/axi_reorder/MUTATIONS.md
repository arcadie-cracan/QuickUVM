# axi_reorder — mutation proofs

The master floats `[0 0 0 1 1 1]` and checks (a) nothing is stranded, (b) same-ID FIFO order,
(c) the round-robin signature: same-id adjacency == 0 (fully interleaved), via `$fatal` so the
regress verdict depends on it. Each mutation is a one-line YAML change (`reorder_policy:`),
regenerated and re-run on Xcelium. The response order is deterministic for `priority` and
`round_robin` (seed-independent) and varies for `random`.

## Baseline — `reorder_policy: round_robin` — PASS

```
[MASTER] recv=[ 0 1 0 1 0 1 ] got=6/6 same-id-adjacency=0 (round_robin expects 0)
UVM_ERROR : 0   UVM_FATAL : 0   (Simulation complete via $finish)
```

Fair interleave; every id served in rotation. Green.

## M1 — `reorder_policy: priority` → GROUPED, adjacency 4, FAIL

Lowest ready id first drains id 0 fully before id 1:

```
[MASTER] recv=[ 0 0 0 1 1 1 ] got=6/6 same-id-adjacency=4 (round_robin expects 0)
[MASTER] beat 1 rid=0, expected 1 -- not round-robin (policy changed?)
Simulation terminated via $fatal(1)
```

`got=6/6` and per-ID FIFO still hold (priority is correct, just grouped); it is the
round-robin *signature* the master rejects — proving the two deterministic policies produce
genuinely different orders from the same backlog.

## M2 — `reorder_policy: random` → varies per seed, FIFO preserved

```
seed=1   recv=[ 0 0 0 1 1 1 ]  adjacency=4
seed=3   recv=[ 0 1 0 1 1 0 ]  adjacency=1
seed=7   recv=[ 0 1 1 0 0 1 ]  adjacency=2
seed=11  recv=[ 0 0 0 1 1 1 ]  adjacency=4
```

Every seed: `got=6/6`, per-ID FIFO intact (no `per-id FIFO broken` $fatal). The interleave
varies with the seed (seeds 1 and 11 happen to land on the grouped `[0 0 0 1 1 1]`); none is the
deterministic round-robin rotation, so the round-robin-expecting master $fatals on all four —
exactly the point: `random` is a distinct policy, not round-robin.

## What every policy shares (the invariants)

No mutation of `reorder_policy` can strand a request or reorder within an id — those are
guaranteed by the scaffold (`STRANDED_REQUESTS` + per-ID `pop_front`), independent of the
arbitration. Break the *drain* instead (as in `../axi_read/MUTATIONS.md` M1) and
`STRANDED_REQUESTS` fires under any policy.
