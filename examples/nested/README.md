# nested — a subsystem of sub-subsystems (H1)

The final H1 example: a **3-level hierarchy**. The top `nested` composes two
sub-subsystems (`clusterA`, `clusterB`); each cluster composes two leaf blocks.

```
nested.yaml                    # top subsystem
  subenvs: [cA -> clusterA, cB -> clusterB]
clusterA.yaml                  # a sub-subsystem
  subenvs: [pa -> a0, qa -> a1]
clusterB.yaml
  subenvs: [pb -> b0, qb -> b1]
a0.yaml a1.yaml b0.yaml b1.yaml   # leaf blocks (each: agent + DUT + scoreboard)
```

A `subenv` may itself be a subsystem — QuickUVM composes recursively (the loader,
generation, and config-db walks all recurse; arbitrary depth).

## What it generates
- **Leaf blocks** (`a0`..`b1`): each a reusable env package (agent VIP + env +
  scoreboard), as for any composed block.
- **Cluster composition classes** (`clusterA_env`, `clusterA_virtual_sequencer`,
  `clusterA_vseq`, …): a cluster env instantiates its leaf envs and collects their
  agent sequencers.
- **Top composition classes** (`nested_env`, …): the top env instantiates the cluster
  envs. Coordination is **hierarchical** — the top vsqr holds each cluster's vsqr and
  the top vseq forks each cluster's vseq; each cluster vseq forks its leaf sequences.
- **`nested_base_test`**: builds the whole env-config **tree** — each level's config is
  set into the config DB at its absolute path (`e.cA`, `e.cA.pa`), leaf agent configs +
  virtual interfaces by full-path key (`cA_pa_ga0_if_vif`); each env self-configures its
  direct children.
- **`tb_top`**: instantiates every **leaf** block's interface + real DUT, with
  path-prefixed names (`cA_pa_ga0_if_inst`, `a0 cA_pa_dut`). The leaf RTL modules stay
  unprefixed and reused.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=nested_test
```
All four leaf-block scoreboards pass **21/21 on Xcelium** (0 errors) — driven
top → cluster → leaf, each leaf checked by its own scoreboard.

## Scope of this slice
- Composition + stimulus recurse to arbitrary depth (validated at 3 levels).
- Every subsystem/block/agent/interface/transaction name must be **unique across the
  whole flattened tree** (they share one output dir + package namespace).
- Fail-closed (deferred): cross-**level** connections/scoreboards (into a subsystem's
  inner blocks), `params` on a nested subsystem, and namespacing (reusing) a nested
  subsystem. A flat single-level subsystem is byte-identical to before.
