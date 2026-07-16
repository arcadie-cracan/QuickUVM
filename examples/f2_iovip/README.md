# f2_iovip — a reusable, versioned agent VIP (F2')

**The reusable component of the F2' VIP-ownership family.** `kind: vip` generates *only* the
reusable `io` agent package + a `.qvip` manifest — no DUT, env, test or top:

```
gen/io_pkg.sv   io_*.svh   io_pkg.f     # the standalone agent VIP (imports only uvm_pkg)
gen/f2_iovip.qvip                        # the manifest: identity + version + package + types
```

It **compiles on its own**: `cd gen && xrun -uvm -compile -F io_pkg.f`.

## Who consumes it

- [`../f2_con`](../f2_con/) — a normal bench that wires the `io` agent in **by reference**
  (`agent_refs:`), without regenerating its source.
- [`../f2_selftest`](../f2_selftest/) — a **DUT-less** self-test of this VIP.

Both point at `gen/f2_iovip.qvip`; edit this VIP once and both see it.

## Why this is *reuse*, not *foldering* (the T3 question)

Before F2', two benches that "reused" an agent each **regenerated their own byte-identical copy** —
foldering. Now the generator emits consumers that share the **one** `io_pkg`. Proven by running it
(see [`docs/t3_tl_agent_assessment.md`](../../docs/t3_tl_agent_assessment.md) §7):

```
edit gen/io_pkg.sv once   -> both consumers fail to elaborate  (they compile the shared source)
delete gen/io_pkg.sv      -> both consumers die                (they depend on the one artefact)
```

If either consumer still built, it had a private copy and the reuse would be an illusion.

## The manifest

`f2_iovip.qvip` records the VIP's identity so a consumer can wire the agent without seeing its
source: `project`, `version`, and per agent its `package`, `filelist`, `interface`,
`sequence_item`, and full `config` (round-tripped back into an `AgentConfig` on the consumer side).
Bump `project.version` to re-identify a changed VIP.

## Regenerate

```
quick-uvm generate -c f2_iovip.yaml -o gen
```
