# pwidth — parameterized agent VIP (C3)

The worked example for **C3** (parameterization). The DUT is incidental (a
combinational `dout = din + 1` at width `W`); the point is that the agent VIP is
`#(W)`-parameterized end to end, so the same VIP is reusable at any width.

## `parameters:` + `width_param:`
`pwidth.yaml` declares a parameter on the agent and references it from the port widths:
```yaml
agents:
  - name: io
    parameters:
      - {name: W, default: 8}   # data width
    ports:
      inputs:  [{name: din,  width_param: W}]
      outputs: [{name: dout, width_param: W}]
```
QuickUVM then generates a parameterized interface **and** parameterized UVM classes:

- `interface io_if #(parameter int W = 8)` with `logic [W-1:0]` signals;
- `class io_seq_item #(parameter int W = 8)` (`uvm_object_param_utils`), `rand bit [W-1:0] din`;
- `io_driver #(W)` / `io_monitor #(W)` / `io_sequencer #(W)` / `io_agent #(W)` /
  `io_cfg #(W)` (`uvm_component_param_utils`), with a `virtual io_if#(W)` handle;
- the env/top instantiate the VIP at the concrete default (`io_agent#(8)`,
  `virtual io_if#(8)`), and the scoreboard types on `io_seq_item#(8)`.

An agent with **no** `parameters` is byte-identical to before — the parameterization is
entirely opt-in.

## Genuinely width-flexible
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
**51/51 on Xcelium** at the default `W=8`. To run at a different width, change the
agent parameter's `default:` in `pwidth.yaml`, set the **DUT**'s `parameter W` to the
same value (the DUT width and the agent width are independent parameters — keep them
equal), and regenerate: the env/top re-emit the concrete `#(16)` instantiations. At
`W=16` it runs **51/51** again — the same VIP, a different width, proving it is truly
parameterized rather than fixed.

*Next:* the C3 Accept criterion is two instances of this VIP at two widths in **one**
bench (the multi-instantiation slice).
