# pipe — cross-block scoreboard over a subsystem pipeline (H1)

Builds on [soc](../soc) (sub-environment composition). Here the composed blocks
form a **pipeline** — stage 1 feeds stage 2 — and a **cross-block scoreboard**
checks the end-to-end behavior across the block boundary.

## `connections:` + `subenv_scoreboards:`
```yaml
# pipe.yaml
subenvs:
  - {name: add, config: add/add.yaml}   # stage 1: dout = din + 1
  - {name: inv, config: inv/inv.yaml}   # stage 2: dout = ~din  (passive agent)
connections:
  - {from: add.dout, to: inv.din}       # stage 1 output drives stage 2 input
subenv_scoreboards:
  - {name: chk, source: add.a, monitor: inv.b}
```

- **`connections:`** — QuickUVM emits the top-level wire in `tb_top`
  (`assign inv_b_if_inst.din = add_a_if_inst.dout;`). Because stage 2's input is
  driven by the connection (not by its agent), stage 2's agent is **passive**
  (`active: false`); QuickUVM emits its input as a monitored (sampled) clockvar and
  its driver drives nothing.
- **`subenv_scoreboards:`** — a cross-block scoreboard `chk` reusing the A2
  two-stream, in-order comparator: it subscribes to stage 1's agent (`source`) and
  stage 2's agent (`monitor`), predicts stage 2's expected output from stage 1's
  stream, and compares. Fill the predict (`pipe_chk_reference_model.svh`):
  `extr.dout = ~t.dout;` — the expected `inv.dout` is `~(add.dout)`.

Each block **also** keeps its own scoreboard (add: `dout==din+1`, inv:
`dout==~din`), so the bench runs **three** scoreboards.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=pipe_test
```
All three scoreboards pass **31/31 on Xcelium** (0 errors): the two block-local
checks and the cross-block `chk` verifying the composed pipeline `inv.dout ==
~(add.dout)`.

## Scope of this slice
- A `connections:` wire drives a destination block's input from a source block's
  output; the destination block's agent on that port must be **passive**.
- A `subenv_scoreboards:` entry is A2 two-stream, **in-order** (a same-cycle /
  combinational pipeline). Out-of-order / latency-windowed cross-block matching and
  the same block reused at N widths are later slices.
- Opt-in: a subsystem with no `connections` / `subenv_scoreboards` is unchanged.
