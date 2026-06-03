# alu — combinational ALU example (S1 motivator)

A combinational ALU (`W=8`): 8 ops (ADD, SUB, AND, OR, XOR, SLL, SRL, SLT) with
Z/C/N/V flags. Three inputs (`a`, `b`, `op`), five outputs (`result` + 4 flags).
Exercises `dut.combinational: true` on a richer shape with non-trivial flag logic.

## Layout
- `rtl/alu.sv` — clean MIT parameterized DUT.
- `alu.yaml` — config (`combinational: true`).
- `gen/` — generated TB; user code is the golden model (`sb_calc_exp`, mirrors the
  RTL including carry/overflow) + the `op inside {0:7}` constraint (`alu_sequence`).
- `sim/xrun.f` — Xcelium filelist.

## Run
```bash
quick-uvm generate -c alu.yaml -o gen
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test     # -> TEST PASSED, 1001/1001
```

## Why this is the S1 motivator
`op` is a plain `rand bit [3:0]`, so the golden model and constraint use **magic
numbers** (`4'd0` = ADD, …) and the valid-opcode constraint lives in the *sequence*
pragma. S1 (typed/enum transaction fields + transaction-level constraints) would let
`op` be an `enum { ADD, SUB, … }`, making the golden/constraint/coverage read by name.
