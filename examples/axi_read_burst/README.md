# axi_read_burst — the AXI epic, slice 2: multi-beat R bursts

The read channel again (`AR → R`), but each read is a **burst**: one `AR` carries a length
`ARLEN`, and the slave answers with `ARLEN+1` `R` data beats, `RLAST` on the last. See
[`docs/axi_epic_assessment.md`](../../docs/axi_epic_assessment.md) for the full epic.

## The one new thing: driving a multi-beat response

[`axi_read`](../axi_read/) drives exactly **one** `R` beat per request (`RLAST` always 1).
A burst response is `ARLEN+1` beats, and nothing in the earlier examples exercised that. It is
expressed in the **driver seam** — the response item already carries `arlen` (copied from the
request), so the driver has everything it needs and no framework change is required:

```systemverilog
// rd_responder_seq.svh — response_logic: build BEAT 0
rsp.rid = req.arid;  rsp.rdata = req.araddr;  rsp.rlast = (req.arlen == 0);  rsp.rvalid = 1;

// rd_driver.svh — drive_item_additional: the generated code drove beat 0; drive the rest
for (int i = 1; i <= int'(tr.arlen); i++) begin
  vif.cb1.rvalid <= 1'b1;
  vif.cb1.rid    <= tr.rid;
  vif.cb1.rdata  <= tr.araddr + i;          // memory model: beat i returns araddr + i
  vif.cb1.rlast  <= (i == int'(tr.arlen));  // RLAST only on the final beat
  @vif.cb1;
end
```

## What runs

`rtl/axi_read_burst.sv` issues M=4 reads **one at a time** (waits for each whole burst before
the next), with `ARLEN` = 0, 3, 1, 2 — bursts of 1, 4, 2, 3 beats, so `ARLEN = 0` and
`ARLEN > 0` are both covered. Per beat it checks `rid`, the memory-model data
(`rdata == araddr + beat`), and that `RLAST` is high **iff** `beat == ARLEN`:

```
read 0 (ARLEN=0): beat0 rdata=0x100 rlast=1
read 1 (ARLEN=3): beat0..3 rdata=0x200..0x203 rlast on beat3
read 2 (ARLEN=1): beat0..1 rdata=0x300..0x301 rlast on beat1
read 3 (ARLEN=2): beat0..2 rdata=0x400..0x402 rlast on beat2
[BURST MASTER] reads=4/4  total R beats=10/10
```

Green on Xcelium: `0 UVM_WARNING / 0 UVM_ERROR / 0 UVM_FATAL`.

One read is outstanding at a time, deliberately, to **isolate bursts** from out-of-order
(that is [`axi_read`](../axi_read/)'s axis). Bursts × out-of-order interleaving — where `R`
beats of different ids interleave — is a later epic slice.

## The verdict is carried by a UVM oracle (not the DUT `$error`)

The automated regression verdict (`make regress`) is **UVM-severity based** — it computes PASS
from the UVM report counts, so a native Verilog `$error` in the DUT is *invisible* to it. If the
burst checks lived only in the DUT, `make regress` would report PASS on a broken burst (a
silent-pass caught by [adversarial review](../../docs/axi_epic_assessment.md)). So the
verdict-carrying check is a **UVM burst oracle in the monitor** (`rd_monitor.svh`): it derives
the expected `R`-beat sequence from the observed `AR` (id, address, length) and raises a
`uvm_error` on a wrong beat, `RLAST`, or count, with a `check_phase` that fails a burst that
never completed. The DUT's own self-check stays as human-readable corroboration — the
[`axi_read`](../axi_read/) split (UVM carries the verdict; the DUT `$display`/`$error`
corroborates).

## Proved it can fail (mutation tests)

Each of the three burst properties is load-bearing — and each mutation flips the **automated
verdict** to FAIL (a verdict-visible `UVM_ERROR` from the oracle, not just a DUT `$error`):

| Mutation | Break | Verdict → FAIL via |
|---|---|---|
| A | drive one too **few** beats (`i < arlen`) | oracle `check_phase`: "ended mid-burst — stranded" (`UVM_ERROR`) |
| B | assert `RLAST` on the wrong beat | oracle "beat 1: rlast=1 expected 0" (`UVM_ERROR`) |
| C | wrong data (`araddr`, not `araddr + i`) | oracle "beat 1: rdata=0x200 expected 0x201" (`UVM_ERROR`) |

Verified end-to-end: on clean the Makefile verdict is PASS (`UVM_ERROR=0`); each mutation makes
it FAIL (`UVM_ERROR` = 1/11/6). The DUT's `$error` corroborates each in the log.

## Scope

Single `ARBURST` type (incrementing, via the `araddr + i` memory model), `ARSIZE` implicit
(full-width beats), no `RRESP` error injection, no ready-handshake backpressure — matching the
family's valid-only simplification. Those, plus bursts crossed with out-of-order, are the
remaining epic slices.

## Layout
- `rtl/axi_read_burst.sv` — the burst-read-master DUT (stimulus + per-beat self-check).
- `axi_read_burst.yaml` — responder config (`respond: pipelined`, `reorder_by: arid`).
- `gen/` — generated TB; user-filled seams are `rd_responder_seq.svh` (beat 0) and
  `rd_driver.svh` (beats 1..arlen).
- `sim/xrun.f` — Xcelium filelist.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=rand_test
```
