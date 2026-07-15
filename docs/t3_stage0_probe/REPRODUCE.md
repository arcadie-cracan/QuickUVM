# T3 Stage-0 probe — is VIP consume-by-reference achievable with today's output?

This is the ½-day experiment that settles T3's core question by construction. It is NOT a
generated bench — the two consumers (`tb_a.sv`, `tb_b.sv`) are **hand-written**, precisely to
show what the generator does *not* yet emit. See [`../t3_tl_agent_assessment.md`](../t3_tl_agent_assessment.md).

## What it proves

Two separate benches consume **one** QuickUVM-generated agent VIP **by reference** — not by
regenerating their own copies. Run on Xcelium 25.09.

## Run it

    # 1. Generate the standalone VIP once (layout: packaged emits io_pkg.sv + io_pkg.f + io_if.sv)
    quick-uvm generate -c vip.yaml -o vip/gen --no-backup

    # 2. Add a version tag to the ONE VIP source (simulates "edit the VIP once"):
    #    in vip/gen/io_pkg.sv, after `import uvm_pkg::*;` add:
    #        localparam string QVIP_TAG = "v1";

    # 3. Build both consumers. Each chains the shared VIP by reference (note -F, capital):
    (cd . && xrun -f tb_a.f)      # prints  QVIP_TAG=v1
    (cd . && xrun -f tb_b.f)      # prints  QVIP_TAG=v1

## The by-reference edge, and the one real gotcha

`tb_a.f` / `tb_b.f` chain the VIP with:

    -F ./vip/gen/io_pkg.f

**`-F` (capital), not `-f`.** Cadence resolves a `-f` file's paths relative to the *current
working directory*; `-F` resolves them relative to *the file's own directory*. The generated
`io_pkg.f` lists `io_if.sv` / `io_pkg.sv` relative to its own `gen/`, so a consumer in another
directory can only reach them via `-F`. With `-f`, elaboration fails with `*SE,FILEMIS`. This is
the concrete thing Stage 1 of the feature must emit correctly — found by running it, not reasoning.

## The two mutations (the actual proof — "reference", not "regeneration")

**M1 — edit once, both see it.** In `vip/gen/io_pkg.sv`, change `QVIP_TAG = "v1"` → `"v2"`.
Rebuild both benches, touch nothing else. **Both print `QVIP_TAG=v2`** ⇒ they compile from the
one shared source, not private copies.

**M2 — delete it, both die.** `rm vip/gen/io_pkg.sv`. **Both benches fail to elaborate**
(`*E`/`FILEMIS`) ⇒ they depend on the one shared artefact. If either still built, it had its own
copy and the seam would be foldering.

## The verdict this settles

The ownership seam **is achievable with today's output shape** — two benches genuinely share one
VIP. So the gap is purely that **the generator will not emit these consumers**: there is no schema
way to say "wire in agent `io` from package `io_pkg`, do not regenerate it" (a bench with
`agents: []` is rejected; declaring the agent regenerates it). The consumers here are hand-written
to stand in for what a `reference:` schema key would generate.
