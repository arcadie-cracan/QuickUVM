# axi_reorder — the `reorder_policy` knob (cross-ID arbitration)

A pipelined responder answers **same-ID** requests in arrival order (`pop_front`) but is free
to reorder **across IDs**. `reorder_policy` chooses that cross-ID arbitration. Same bench as
[`../axi_read/`](../axi_read/), but the DUT master floats a backlog with **repeated ids** (3
reads on id 0, then 3 on id 1) so the policy is visible in the response order.

```yaml
respond: pipelined
reorder_by: arid
reorder_policy: round_robin   # priority (default) | round_robin | random
```

| policy | rule | this backlog → recv order | property |
|---|---|---|---|
| `priority` (default) | lowest ready id first | `[0 0 0 1 1 1]` (grouped) | deterministic; a high id can starve under *sustained* low-id arrival (not this fixed backlog) |
| `round_robin` *(this bench)* | next id after the last, wrapping | `[0 1 0 1 0 1]` (interleaved) | deterministic; **fair**, no starvation |
| `random` | any ready id | varies per seed | matches PULP's `axi_rand_slave` |

Under **every** policy the invariants hold: no request is stranded (`STRANDED_REQUESTS`
guards it) and same-ID responses keep arrival order. Only the cross-ID interleave changes.

## What the run shows (Xcelium, round_robin)

```
[MASTER] recv=[ 0 1 0 1 0 1 ] got=6/6 same-id-adjacency=0 (round_robin expects 0)
```

The master floats `[0 0 0 1 1 1]`; round-robin returns them fully interleaved (`same-id
adjacency = 0`). The master **$fatals** if the adjacency is not 0, so the regress verdict
genuinely gates round-robin behaviour — flip the policy and it fails (see [`MUTATIONS.md`](MUTATIONS.md)).

## How round-robin is generated

`reorder_policy: round_robin` adds a cursor (`m_last_id`) to the responder sequence and picks
the next ready id strictly above it, wrapping to the lowest when none is:

```
pick = -1;
foreach (ready[i]) if (ready[i] > m_last_id && (pick == -1 || ready[i] < pick)) pick = ready[i];
if (pick == -1) begin pick = <lowest ready id>; end   // wrap
m_last_id = pick;
```

`priority` needs no state (lowest ready id); `random` is `ready[$urandom_range(...)]`.

## Run it

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
# or the seed regression:
cd ../gen && make regress
```
