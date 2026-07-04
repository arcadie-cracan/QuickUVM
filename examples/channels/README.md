# channels — the same block reused at N widths (H1)

Builds on [psoc](../psoc) (parameter propagation). Here **one** parameterized
block config is composed **more than once** in a subsystem, at different widths —
two identical channels at W=8 and W=16 — from a single config and a single RTL
module.

## Reuse by referencing the same config
```yaml
# channels.yaml
subenvs:
  - {name: lo, config: chan/chan.yaml, params: {W: 8}}
  - {name: hi, config: chan/chan.yaml, params: {W: 16}}
```
Both subenvs point at the **same** `chan/chan.yaml`. Two copies of a block's env
would normally collide (same `chan_env`, `c_seq_item`, `c_if`, … class names), so
QuickUVM detects the shared config and **auto-namespaces** each instance's classes
by its subenv name:

- `lo` → `lo_chan_env`, `lo_c_agent`, `lo_c_if`, `lo_c_seq_item#(8)`, `lo_chan_env_pkg`
- `hi` → `hi_chan_env`, `hi_c_agent`, `hi_c_if`, `hi_c_seq_item#(16)`, `hi_chan_env_pkg`

The reused **RTL DUT module stays unprefixed** — both instances reuse the one
`chan` module, instantiated `chan#(8) lo_dut` and `chan#(16) hi_dut`. Each instance
keeps its own scoreboard, at its own width.

## Simple by default, powerful when needed
Auto-namespacing engages only for a **shared** config; a config used once is never
prefixed (so the other subsystem examples are byte-identical). Override per subenv:

- `namespace: true` — force namespacing (by the subenv name) even for a single use;
- `namespace: <prefix>` — force a custom class prefix;
- `namespace: false` — disable it (a genuine collision then fails closed).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=channels_test
```
Both channels pass **31/31 on Xcelium** (0 errors) — an 8-bit and a 16-bit channel,
each checked by its own scoreboard, from **one** block config and **one** RTL module.

## Scope of this slice
- A shared `config` path is auto-namespaced; `namespace` overrides it.
- A namespaced (reused) block may **not** yet be referenced by a cross-block
  `connection` / `subenv_scoreboard` (its agent names are prefixed).
- Namespaced top-internal instance/handle names are double-prefixed (`lo_lo_c_if_inst`)
  — cosmetic; the class/type names carry a single clean prefix.
