# psoc — parameter propagation into composed blocks (H1)

Builds on [soc](../soc) (sub-environment composition). Here the composed blocks
are **parameterized**, and the subsystem **propagates a width to each block**.

## `params:` on a subenv
```yaml
# psoc.yaml
subenvs:
  - {name: dp,  config: dp/dp.yaml,   params: {W: 8}}
  - {name: mac, config: mac/mac.yaml, params: {W: 16}}
```
`dp/dp.yaml` and `mac/mac.yaml` are reusable, **width-parameterized** block
benches (their agent declares `parameters: [{name: W, default: 8}]`, see the
[pwidth](../pwidth) example for the C3 mechanism). The `params:` override on each
subenv bakes that instance's width into the block's agent parameter default, so
the whole block env is generated at that width:

- `dp` at **W=8** — `d_seq_item#(8)`, `d_if#(8)`, `dp#(8)` DUT, scoreboard on `#(8)`;
- `mac` at **W=16** — `m_seq_item#(16)`, `m_if#(16)`, `mac#(16)` DUT, scoreboard on `#(16)`.

The top threads the concrete width everywhere it names a block's interface, DUT,
sequencer or sequence: `tb_top` instantiates `d_if#(8)` / `m_if#(16)` and
`dp#(8)` / `mac#(16)`; the `psoc_virtual_sequencer` holds `d_sequencer#(8)` /
`m_sequencer#(16)`; the `psoc_vseq` starts `d_seq#(8)` / `m_seq#(16)`.

A **non-parameterized** block is byte-identical to before — the propagation is
entirely opt-in.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=psoc_test
```
Both blocks pass **31/31 on Xcelium** (0 errors) — an 8-bit datapath and a 16-bit
datapath, each checked by its own scoreboard, from the same reusable block
configs propagated to different widths.

## Scope of this slice
- Per-subenv override of a block's parameters; the block is generated at that width.
- A parameterized block must be **single-agent** (the DUT's `#()` args come from the
  sole agent); a `params:` key must name a declared block parameter. As in C3, the
  DUT is instantiated with positional args, so a multi-parameter block's agent
  `parameters:` order must match the DUT module's parameter order.
- Not yet: the **same** block config reused at N widths in one subsystem (that needs
  per-instance class namespacing), nested subenvs, and cross-block scoreboards.
