# f2_selftest — a DUT-less VIP self-test (F2')

`kind: selftest` exercises the `io` VIP (consumed by reference from [`../f2_iovip`](../f2_iovip/))
with **no DUT**. The generated top instantiates the VIP interface and wires a **loopback** seam
instead of a DUT; the io agent drives `din`, the loopback returns it on `dout`, and the scoreboard
checks it. **101/101 on Xcelium** — the reusable VIP validated stand-alone.

```
gen/tb_top.sv     # loopback top: `assign io_if_inst.dout = io_if_inst.din;`  (no dut_inst)
                  # no f2_selftest.sv DUT stub
```

**M3 — it actually tests.** Corrupt the loopback (`dout = ~din`) and the test goes red (102
UVM_ERRORs), not a silent pass — the dead-responder trap has teeth here.

## Run

```
cd gen && xrun -uvm -access +rwc -f run.f +UVM_TESTNAME=rand_test
```
