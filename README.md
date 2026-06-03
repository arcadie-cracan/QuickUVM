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

## Design philosophy — simple by default, powerful when needed

QuickUVM aims to keep the promise in its name — **quick adoption, low barrier to entry, a
gentle learning curve** — while scaling up to complex, industrial-grade functional
verification. Borrowing the KDE Community principle, it should be **simple by default and
powerful when needed**: trivial for a student or a single-block bring-up, yet capable of
growing into a full industrial environment.

This is a design constraint on every feature, not just a slogan:

- **The simple path stays simple.** A few lines of YAML produce a running bench; the flat,
  single-package default is never harder to reach because advanced capability exists.
- **Complexity is opt-in and additive.** New capabilities (multi-agent analysis, register
  models, …) are off by default and leave output **byte-identical** when unused —
  progressive disclosure, never a tax on the basic case.
- **Sane defaults, with escape hatches.** Good defaults out of the box; the escape hatch
  for arbitrary complexity is the pragma/user-code regions, not an ever-growing config.
- **Useful in education *and* industry.** The teaching/small-block use case is a
  first-class goal, not a stepping stone to be engineered away.

Every roadmap phase (see [`docs/parity_roadmap.md`](docs/parity_roadmap.md)) is judged
against this "simplicity budget."

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
  uvm_version: "1.2"   # "1.2" (default) or "1.1d" — selects version-specific UVM APIs

dut:
  name: simple_reg
  clock: clk
  reset: rst_n
  reset_active_low: true
  external_reset: false  # opt-in: reset is driven by a top-level reset generator
                         # (not the agent). When true, QuickUVM declares the reset
                         # as an interface port, generates a reset_generator in top,
                         # and reset-gates the driver + monitor. Leave false when the
                         # reset is an agent input port or handled in user pragma code.
  combinational: false   # opt-in: the DUT is purely combinational (no clock/reset).
                         # The clock is kept as a TB cadence (one vector/cycle) but
                         # NOT connected to the DUT; the stub is always_comb; and the
                         # monitor samples inputs+outputs together (0-cycle latency)
                         # race-free via a monitor clocking block. The cadence period
                         # must exceed the DUT's combinational settling time.

clock:
  period: 10
  unit: ns
  drive_offset_pct: 20

agents:
  - name: reg
    interface: reg_if
    transaction: reg_seq_item
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
  frontdoor: reg_frontdoor             # generate+install a custom uvm_reg_frontdoor (body = pragma)
```

See [`examples/simple_reg/`](examples/simple_reg/) for a working example.

---

## Generated file set

For each agent `<ag>` and test `<t>`, QuickUVM generates:

```
clkgen.sv         <dut>.sv (stub)
<ag>_if.sv        <ag>_seq_item.svh <ag>_sequencer.svh
<ag>_driver.svh   <ag>_monitor.svh  <ag>_agent.svh
<ag>_cover.svh    <ag>_sequence.svh
sb_predictor.svh  sb_comparator.svh tb_scoreboard.svh
sb_calc_exp.svh   env.svh           test_base.svh
<t>.svh           top.sv            tb_pkg.sv
pkg.f             run.f
```

---

## Coding standards

QuickUVM has two codebases with different stakes, plus the Jinja bridge — each has a
short, **tool-enforced** style guide (CI runs them on every PR):

- [`docs/style_python.md`](docs/style_python.md) — the generator: **Ruff** (format + lint)
  + **mypy** (lenient→ratchet), via `pre-commit` and CI.
- [`docs/style_systemverilog.md`](docs/style_systemverilog.md) — the **generated UVM**
  (the product): Cliff Cummings / Sunburst baseline, 100-column, `_seq_item` transaction
  naming, gated by **Verible** lint in CI.
- [`docs/style_templates.md`](docs/style_templates.md) — `*.j2` template hygiene
  (no `{%-` strips, isolated pragma markers, deterministic output).

The generated output follows the Paradigm Works flat-package style: all components in a
single `tb_pkg.sv`, interface passing via `uvm_config_db`, clocking-block-driven I/O, and
`extern` method bodies in separate `.svh` files.

---

## License

The `uvmtb_template/` reference files are copyright Paradigm Works / Cliff Cummings and included here for reference only — see [`uvmtb_template/LICENSE`](uvmtb_template/LICENSE).

The QuickUVM generator code (`quick_uvm/`, `tests/`, `examples/`, templates) is released under the MIT License — see [`LICENSE`](LICENSE).
