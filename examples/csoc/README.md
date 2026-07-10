# csoc — a clocked subsystem (H1 × M1)

A subsystem that composes **clocked** leaf blocks — the H1 combinational-only
restriction lifted, meeting M1. The top is a combinational shell (like
[`soc`](../soc/)) but its two children are registered, each on its **own** clock +
external reset.

```
csoc.yaml                      # combinational top (no clock/reset of its own)
  subenvs:
    - {name: acc, config: acc.yaml}   # registered, clock @10ns, external reset
    - {name: mul, config: mul.yaml}   # registered, clock @8ns,  external reset
```

Each clocked leaf declares its own clock + reset in its **own** yaml (exactly the
shape of a standalone clocked bench). QuickUVM flattens them into one `tb_top` and,
per clocked leaf, generates a **pathname-prefixed** clock/reset domain:

```systemverilog
  logic acc_clk;    logic acc_rst_n;
  logic mul_clk;    logic mul_rst_n;
  clkgen #(10) ck_acc_clk (acc_clk);      // acc's own 10 ns clkgen
  clkgen #(8)  ck_mul_clk (mul_clk);      // mul's own 8 ns clkgen
  // reset generator per leaf, each synced to its own clock (own pragma region)
  a_if acc_a_if_inst (.clk(acc_clk), .rst_n(acc_rst_n));
  m_if mul_m_if_inst (.clk(mul_clk), .rst_n(mul_rst_n));
```

- **Per-leaf independent domains** — `acc` runs at 10 ns and `mul` at 8 ns, two
  genuinely independent clock domains in one subsystem. Prefixing by the subenv
  path makes the nets tree-unique (two leaves that both default `rst_n` never
  collide).
- **The leaf VIP layer is already clocked-ready** — a composed clocked leaf's
  interface carries its reset port and its driver/monitor reset-gate for free (the
  per-agent clock/reset view flows into leaf generation). The subsystem `tb_top`
  only had to add the physical clock/reset wiring.
- **The top owns the reset generators** (moved from each leaf, which emits none in
  composed mode).

A fully **combinational** subsystem (`soc`/`nested`/…) is byte-identical — the
clock/reset block appears only when a leaf is clocked.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=csoc_test
```
Both leaf scoreboards (`acc` @10 ns, `mul` @8 ns) pass **on Xcelium** (0 errors).

## Scope / notes
- Fail-closed: a composed clocked leaf must be single-clock, at most one reset, and
  share the subsystem's time unit (ns here).
- Deferred: mixed-unit / nested-multi-clock clocked leaves; a clocked leaf with a
  register model or multi-instantiated agents.
