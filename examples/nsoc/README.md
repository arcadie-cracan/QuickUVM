# nsoc — a parameterized, reused nested subsystem (H1)

Combines two H1 capabilities on a *nested* subsystem: **reuse** (compose the same
sub-subsystem more than once) and **parameter propagation** (push a width down to
its blocks).

```
nsoc.yaml                       # top
  subenvs:
    - {name: lo, config: chan.yaml, params: {W: 8}}
    - {name: hi, config: chan.yaml, params: {W: 16}}   # SAME cluster, twice
chan.yaml                       # a parameterized sub-subsystem
  subenvs: [adder -> add.yaml, shifter -> shl.yaml]
add.yaml shl.yaml               # parameterized leaf blocks (width W)
```

Both subenvs point at the **same** `chan.yaml` (an adder + a shifter, each width `W`).
QuickUVM detects the shared cluster config and:

- **auto-namespaces the whole cluster subtree** by the subenv name — `lo_chan`
  composes `lo_add` + `lo_shl` (agents `lo_a`/`lo_s`); `hi_chan` composes `hi_add` +
  `hi_shl`. Prefixes **stack** if a cluster is also internally reused;
- **propagates the width to every leaf agent** — `lo` runs at W=8, `hi` at W=16;
- **recovers the reused RTL module names unprefixed** — both instances reuse the one
  `add` / `shl` module, instantiated `add#(8)` (lo) and `add#(16)` (hi). The original
  module name is captured once, before any prefix, so it survives however many
  prefixes stack.

The whole thing is three recursive model transforms — **no template changes** — and is
byte-identical for every non-reused / non-parameterized bench (the recursion is a no-op
when the prefix is empty and there are no params).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=nsoc_test
```
All four leaf-block scoreboards pass **21/21 on Xcelium** (0 errors) — an 8-bit channel
and a 16-bit channel, from **one** cluster config and **one** RTL module per block.

## Scope / notes
- Reuse + params on a nested subsystem recurse to arbitrary depth; a `params:` key that
  no descendant agent declares is rejected (fail-closed).
- Top-internal instance/handle names are path-prefixed (and long lines are wrapped for
  lint under deep nesting); the class/type names carry the stacked prefix.
- Still deferred: cross-**level** connections/scoreboards (into a subsystem's inner blocks).
