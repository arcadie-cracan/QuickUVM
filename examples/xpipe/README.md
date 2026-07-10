# xpipe — cross-level connections & scoreboards (H1)

A cross-level version of [`pipe`](../pipe/): the pipeline stages live *inside*
nested subsystems, and a `connections:` wire plus a `subenv_scoreboards:` check
reach across the hierarchy into their leaf blocks.

```
xpipe.yaml                          # top
  subenvs: [stg1 -> stg1.yaml, stg2 -> stg2.yaml]
  connections:        [{from: stg1.add.dout, to: stg2.inv.din}]   # cross-level
  subenv_scoreboards: [{name: xchk, source: stg1.add.a, monitor: stg2.inv.b}]
stg1.yaml   # cluster: add (dout=din+1) + dbl (dout=din<<1)
stg2.yaml   # cluster: inv (dout=~din, PASSIVE) + xr (dout=din^A5)
```

An endpoint is a **dotted path** resolved relative to the level that declares it.
`stg1.add.dout` descends `stg1 → add` and names port `dout`. A same-level
`add.dout` is just a 1-segment path, so the flat `pipe` bench stays byte-identical.

- **The wire** `stg1.add.dout -> stg2.inv.din` becomes a flattened `tb_top` assign
  between the real leaf interface instances:
  `assign stg2_inv_b_if_inst.din = stg1_add_a_if_inst.dout;` — the physical
  signals the flattening already instantiates. `tb_top` gathers every level's
  wires, each prefixed by its path from the top.
- **The scoreboard** `xchk` emits at the top env with a dotted child-env **handle
  chain**: `stg1.add.a_agnt.ap.connect(xchk.src_axp)` (and `stg2.inv.b` for the
  monitor) — reachable because each child env is a handle named for its subenv. It
  predicts `inv.dout = ~(add.dout)` from add's stream and compares (A2 two-stream,
  in-order).

`inv` is the wire's destination, so its agent is **passive** (the connection, not
the agent, drives `inv.din`); `dbl` and `xr` are independent blocks that make each
cluster a real subsystem (`>= 2` blocks) and keep their own self-check.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=xpipe_test
```
All five scoreboards pass **31/31 on Xcelium** (0 errors) — the four leaf
self-checks (`add`, `dbl`, `inv`, `xr`) plus the cross-level **`xchk`** spanning
both clusters (`uvm_test_top.e.xchk`).

## Scope / notes
- Endpoints reach a leaf at any depth; a connection/scoreboard may be declared at
  any composition level and resolves against that level's own subtree.
- Fail-closed: naming a subsystem directly (must descend to a leaf), an unknown
  segment, or any segment in a **reused** (namespaced) subtree — cross-level into a
  reused subsystem is a later slice.
