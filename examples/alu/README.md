# alu — combinational ALU example (named opcodes; S1 motivator)

A combinational ALU (`W=8`): 8 ops (ADD, SUB, AND, OR, XOR, SLL, SRL, SLT) with
Z/C/N/V flags. Three inputs (`a`, `b`, `op`), five outputs (`result` + 4 flags).
Exercises `dut.combinational: true` on a richer shape with non-trivial flag logic.

Operations are **named** via `alu_pkg::opcode_e` (an enum typedef) rather than magic
numbers — used by the DUT *and* the testbench, so the logic reads by name everywhere
(coding guideline: prefer enums/named constants over numbers — `docs/style_systemverilog.md`).

## Layout
- `rtl/alu_pkg.sv` — shared `opcode_e` enum (named opcodes).
- `rtl/alu.sv` — clean MIT parameterized DUT (`case (opcode_e'(op)) ADD: …`).
- `alu.yaml` — config (`combinational: true`).
- `gen/` — generated TB; user code:
  - `tb_pkg.sv` `imports` pragma — `import alu_pkg::*;`
  - `sb_calc_exp.svh` `prediction_logic` — golden model (mirrors the RTL, named ops).
  - `alu_sequence.svh` `do_item_constraints` — `op inside {[ADD:SLT]}`.
- `sim/xrun.f` — Xcelium filelist (`alu_pkg.sv` compiled before `tb_pkg`).

## Run
```bash
quick-uvm generate -c alu.yaml -o gen
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test     # -> TEST PASSED, 1001/1001
```

## Still the S1 motivator
The opcodes are named, but the transaction *field* `op` is still a generated
`rand bit [3:0]`, so a valid-opcode constraint is needed and lives in the sequence
pragma. S1 (typed/enum transaction fields) would make `op` an `opcode_e` rand field that
**self-constrains** to legal values — no separate constraint, and coverage derivable
from the enum.
