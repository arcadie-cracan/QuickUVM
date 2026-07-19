# nchan — the `replicas` feature: N agents into ONE vectored DUT (I-9)

**Can one agent definition be replicated N times into a single DUT with vectored ports?** Yes
— this is `replicas: N`, the last of `alert_handler`'s three gaps (I-9). OpenTitan's alert_handler
instantiates *one* `alert_esc_agent` ~63 times, one per alert line, into one block. QuickUVM's C3
`instances` gave each instance its own DUT; `replicas` shares **one** DUT, each replica bound to a
slice of its vectored ports.

```yaml
agents:
  - name: ch
    replicas: 3            # 3 identical channels -> DUT ports become [2:0]
    ports:
      inputs:  [{name: d, width: 1}, {name: v, width: 1}]
      outputs: [{name: q, width: 1}]
```

generates 3 interfaces, 3 agents, 3 per-channel scoreboards — and **one** DUT:

```systemverilog
nchan dut_inst (
  .q({ ch_2_if_inst.q, ch_1_if_inst.q, ch_0_if_inst.q }),   // replica i <-> bit i
  .d({ ch_2_if_inst.d, ch_1_if_inst.d, ch_0_if_inst.d }),
  .v({ ch_2_if_inst.v, ch_1_if_inst.v, ch_0_if_inst.v }),
  .clk(clk), .rst_n(rst_n)
);
```

The DUT (`rtl/nchan.sv`) is N independent 1-bit latch channels (`q[i] <= d[i]` on `v[i]`). Each
replica drives/samples its own channel; each per-channel scoreboard checks its own slice.
**3×102/102 on Xcelium, 0 errors** (`make regress` 2/2).

## How it's built

`replicas` reuses the C3 `instances` machinery — the env, config, per-instance agents, per-instance
scoreboards, and per-instance sequences are all the C3 wiring. The one new piece is tb_top: instead
of C3's *one DUT per instance*, `replicas` binds all N interfaces to **one** DUT via a concatenation
(`{inst_{N-1}, .., inst_0}`), so replica *i* maps to bit *i* of each vector port.

## Mutation proof — per-channel independence + correct index mapping

[MUTATIONS.md](MUTATIONS.md): break **only channel 1** (`q[1] <= ~d[1]`), and **only `ch_1`'s
scoreboard fails** (196 errors, all from `nchan_ch_1_comparator`) while ch_0 and ch_2 stay green.
That proves both that the per-channel scoreboards are independent *and* that the vectored binding
maps replica *i* to bit *i* (channel 1 → `ch_1` → `dut.q[1]`).

## Run

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
# or the seed regression:
cd ../gen && make regress
```
