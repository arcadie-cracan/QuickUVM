# QuickUVM

A Python/Jinja2 UVM testbench generator based on the
[Paradigm Works `uvmtb_template`](https://github.com/cliffordcummings/uvmtb_template)
style (Cliff Cummings / Sunburst Design).

User-written code is preserved across regenerations via **pragma sections**
inspired by the Siemens UVMF framework:

```systemverilog
// pragma quickuvm custom prediction_logic begin
  // your code here — survives every `quick-uvm generate`
// pragma quickuvm custom prediction_logic end
```

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
```

Or in editable / dev mode:

```bash
pip install -e ".[dev]"
```

**Requirements:** Python ≥ 3.10, Jinja2, PyYAML, Click, Pydantic v2.

---

## Quick start

```bash
# 1. scaffold a config
quick-uvm init --name my_dut --output my_dut.yaml

# 2. edit my_dut.yaml (ports, tests, …)

# 3. generate the testbench
quick-uvm generate --config my_dut.yaml --output tb/

# 4. add your logic inside the pragma sections, then regenerate freely
quick-uvm generate --config my_dut.yaml --output tb/
```

---

## CLI reference

| Command | Description |
|---|---|
| `quick-uvm generate` | Generate (or regenerate) all testbench files |
| `quick-uvm init` | Scaffold a starter YAML config |
| `quick-uvm list` | List files that would be generated (dry-run table) |
| `quick-uvm add-test` | Append a new test to the config and regenerate test files |
| `quick-uvm status` | Show which user pragma sections have been modified |

Run `quick-uvm <command> --help` for full option details.

---

## Config format

```yaml
project:
  name: simple_reg
  author: you
  year: 2026

dut:
  name: simple_reg
  clock: clk
  reset: rst_n
  reset_active_low: true

clock:
  period: 10
  unit: ns
  drive_offset_pct: 20

agents:
  - name: reg
    interface: reg_if
    transaction: reg_trans
    trans_style: manual   # or field_macros
    active: true
    ports:
      inputs:
        - name: din
          width: 16
          randomize: true
        - name: rst_n
          width: 1
          randomize: true
      outputs:
        - name: dout
          width: 16
          randomize: false

tests:
  - name: test_rand
    num_items: 100
```

See [`examples/simple_reg/`](examples/simple_reg/) for a working example.

---

## Generated file set

For each agent `<ag>` and test `<t>`, QuickUVM generates:

```
CYCLE.sv          clkgen.sv         <dut>.sv (stub)
<ag>_if.sv        <ag>_trans.svh    <ag>_sequencer.svh
<ag>_driver.svh   <ag>_monitor.svh  <ag>_agent.svh
<ag>_cover.svh    <ag>_sequence.svh
sb_predictor.svh  sb_comparator.svh tb_scoreboard.svh
sb_calc_exp.svh   env.svh           test_base.svh
<t>.svh           top.sv            tb_pkg.sv
pkg.f             run.f
```

---

## Template style

Templates strictly follow the Paradigm Works flat-package style:
- All components included in a single `tb_pkg.sv`
- `uvm_resource_db` for interface passing
- Clocking-block driven I/O
- `extern` method bodies in separate `.svh` files

---

## License

The `uvmtb_template/` reference files are copyright Paradigm Works / Cliff Cummings and included here for reference only — see [`uvmtb_template/LICENSE`](uvmtb_template/LICENSE).

The QuickUVM generator code (`quick_uvm/`, `tests/`, `examples/`, templates) is released under the MIT License — see [`LICENSE`](LICENSE).
