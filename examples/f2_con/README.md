# f2_con — consume an agent VIP BY REFERENCE (F2')

A normal bench that wires the `io` agent from [`../f2_iovip`](../f2_iovip/) **by reference**:

```yaml
agent_refs:
  - {name: io, manifest: ../f2_iovip/gen/f2_iovip.qvip}
```

The loader reads the manifest, reconstructs the `io` agent, and appends it to the env — so this
bench **imports `io_pkg` and instantiates `io_agent`**, but its `gen/` contains **no `io_*.svh` /
`io_pkg.sv`**: the source is not regenerated. The env filelist chains the VIP with Cadence `-F`:

```
gen/f2_con_env_pkg.f:   -F ../../f2_iovip/gen/io_pkg.f
```

The stub DUT is a trivial loopback (`dout = din`); the reused io agent drives `din`, samples `dout`,
and the scoreboard checks it. **101/101 on Xcelium.**

Edit `../f2_iovip/gen/io_pkg.sv` and this bench sees it; delete it and this bench fails to
elaborate — the M1/M2 proof of *reference, not regeneration*
([`docs/t3_tl_agent_assessment.md`](../../docs/t3_tl_agent_assessment.md) §7).

## Run

```
cd gen && xrun -uvm -access +rwc -f run.f +UVM_TESTNAME=rand_test
```
