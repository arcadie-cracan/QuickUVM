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

Preservation is **fail-closed**: if a regeneration would orphan code you wrote (a
section the new template no longer emits) or finds a malformed marker, `generate`
aborts before writing anything, and a rolling `<file>.bak.<N>` backup is taken on every
overwrite (existing backups are never overwritten).
See [`docs/code_preservation.md`](docs/code_preservation.md) for the full contract, the
list of available sections, and the `status` command; a comparison against UVMF, Doulos
Easier UVM, icdk uvmgen and gen_uvm is in [`docs/comparison.md`](docs/comparison.md).

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
| `quick-uvm generate` | Generate (or regenerate) all files. Fail-closed; `--allow-drop` / `--no-backup` to override |
| `quick-uvm init` | Scaffold a starter YAML config |
| `quick-uvm list` | List files that would be generated (dry-run table) |
| `quick-uvm add-test` | Append a new test to the config and regenerate test files |
| `quick-uvm status` | Classify each file: user-modified / orphaned / out-of-band / malformed markers |

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

# Optional — declarative analysis routing (multi-agent). When omitted, a single
# scoreboard + coverage collector are wired to the first agent (legacy behaviour).
analysis:
  coverage: [reg]                 # one <agent>_cover per listed agent
  scoreboards:
    - {name: sbd, source: reg}    # tb_scoreboard fed by <source>.ap

# Optional — front-door register model (RAL). The uvm_reg_block is generated
# externally (e.g. reggen/SystemRDL); QuickUVM generates the adapter skeleton
# (reg2bus/bus2reg = pragma sections you fill), env/test wiring, and a reg test.
register_model:
  package: angle_sensor_regs_uvm_pkg   # external uvm_reg package to import
  block:   angle_sensor_regs_c         # uvm_reg_block class
  map:     default_map
  bus_agent: reg                       # agent whose sequencer drives front-door
  adapter:   reg_adapter
  use_predictor: true                  # explicit prediction via the agent ap
  reg_test:      true                  # generate hw_reset + bit_bash test
  # Backdoor (optional): point at the regfile instance so peek/poke hit RTL
  # storage (needs the reg block to carry hdl_path slices). reg_test_door=backdoor
  # runs the register test via backdoor (sidesteps bus protocol quirks).
  backdoor_root: top.dut_inst.regs_inst
  reg_test_door: backdoor              # frontdoor (default) | backdoor
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
