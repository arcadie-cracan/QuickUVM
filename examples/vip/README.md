# vip — packaged testbench layout (F2)

The worked example for **F2** (`layout: packaged`). The DUT is incidental (a
combinational `dout = din + 1`); the point is the **packaged** TB structure — the flat
`<dut>_tb_pkg` is split into separately-compilable SystemVerilog packages, each with its
own `.f` filelist, so the agent VIP is reusable across projects.

## flat → packaged
`vip.yaml` sets `layout: packaged`. Instead of one `vip_tb_pkg` that includes
everything, QuickUVM emits:

| Package | Contains | Imports |
|---|---|---|
| `io_pkg` | the `io` agent VIP: seq_item, cfg, cov, sequencer, driver, monitor, agent, sequences | `uvm_pkg` (+ the `io_if` interface, compiled alongside) |
| `vip_env_pkg` | scoreboard (predictor/comparator/scoreboard + reference model) + env | `uvm_pkg`, every `<agent>_pkg` |
| `vip_test_pkg` | base test + tests | `uvm_pkg`, `vip_env_pkg`, the agent packages |

with a per-package filelist each (`io_pkg.f`, `vip_env_pkg.f`, `vip_test_pkg.f`) chained
via `-f`, and a thin `tb_top` that just imports the test package. `layout: flat` (the
default) keeps the single `vip_tb_pkg` — byte-identical to every other example.

## The agent VIP compiles standalone
That is the F2 Accept criterion — the reusable VIP has no env/test dependencies:
```sh
cd gen
xrun -uvm -compile -f io_pkg.f      # → io_pkg: 0 errors
```
The per-package `.f` files resolve their nested `-f` relative to the cwd, so run them
from `gen/`. (`gen/vip_env_pkg.f` and `gen/vip_test_pkg.f` chain the layers.)

## Run the full bench
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
**51/51 on Xcelium, 0 errors.** `sim/xrun.f` lists the packages directly in dependency
order (so it runs from `sim/` against the real `rtl/vip.sv`); the generated `.f` chain
is the separate-compilation path, run from `gen/`.
