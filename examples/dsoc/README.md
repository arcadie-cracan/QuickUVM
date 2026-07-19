# dsoc — cross-level into a reused (namespaced) subtree (H1)

Combines [same-block reuse](../channels/) with [cross-level wiring](../xpipe/): the
top reuses the **same** `lane` cluster twice and wires the two instances together
across the hierarchy.

```
dsoc.yaml                            # top
  subenvs: [left -> lane.yaml, right -> lane.yaml]   # SAME cluster, twice
  connections:                                        # a cross-instance ring
    - {from: left.src.dout,  to: right.snk.din}
    - {from: right.src.dout, to: left.snk.din}
  analysis:
    scoreboards:
      - {name: l2r, source: left.src.sa,  monitor: right.snk.ka}
      - {name: r2l, source: right.src.sa, monitor: left.snk.ka}
lane.yaml   # cluster: src (dout=din+1, active) + snk (dout=~din, PASSIVE)
```

Because `lane` is composed twice, its whole subtree is **auto-namespaced**
(`left_*` / `right_*`). A cross-level endpoint still reads exactly like a
non-reused one:

- **The path** (`left.src`) uses subenv **instance** names, which reuse
  preserves — so it disambiguates *which* instance for free (`left.src` vs
  `right.src`).
- **The leaf agent** is named by its **original** name (`sa`, `ka` — as declared
  in `src.yaml`/`snk.yaml`), *not* the mangled `left_sa`. QuickUVM captures each
  agent's original name when it applies the prefix and maps it back, so the
  `left_`/`right_` prefix stays a fully internal artifact.

The generated output carries the prefix where it must:

```systemverilog
// tb_top ring wire (namespaced leaf interface instances)
assign right_snk_right_snk_if_inst.din = left_src_left_src_if_inst.dout;
// dsoc_env scoreboard connect (prefixed agent handle, plain path)
left.src.left_sa_agnt.ap.connect(l2r.src_axp);
```

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=dsoc_test
```
All six scoreboards pass **31/31 on Xcelium** (0 errors) — the four leaf
self-checks plus the two cross-level, cross-instance scoreboards (`l2r`, `r2l`)
that span the two reused `lane` instances.

## Scope / notes
- Wires needed nothing beyond the resolver descending into the namespaced
  subtree (ports are never mangled; the resolved leaf's prefixed interface
  already names the tb_top instance).
- Fail-closed: a trailing agent token matching neither the original nor the
  prefixed name is still rejected.
- This closes the last deferred H1 combination — see `docs/parity_roadmap.md`.
