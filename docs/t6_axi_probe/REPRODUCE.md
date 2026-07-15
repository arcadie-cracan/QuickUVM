# T6 probe — the multi-outstanding OoO responder strands its burst

Evidence for [`../t6_axi_outstanding_assessment.md`](../t6_axi_outstanding_assessment.md). Shows,
on Xcelium, that a QuickUVM `respond: on_request` responder **cannot** answer a finite burst of N
outstanding requests out of order — the generated loop answers one per incoming request and strands
the rest.

## Run it

    quick-uvm generate -c axi_read.yaml -o gen --no-backup
    # (the config has analysis.scoreboards: [] — the DUT master self-checks)
    # paste responder_seams.sv's two blocks into gen/rd_responder_seq.svh's
    #   class_item_additional and response_logic pragma regions.
    xrun -uvm -timescale 1ns/1ns -top tb_top +incdir+gen \
         gen/rd_if.sv gen/clkgen.sv axi_read.sv gen/axi_read_tb_pkg.sv gen/tb_top.sv \
         +UVM_TESTNAME=rand_test

## What you see — the strand

    [RESP  155] DRIVE one rsp rid=2, but outstanding=2 STILL QUEUED
    [MASTER ...] got 1 R beat, expected 3    (the 2 queued requests are never answered)

The `request_fifo` (a `uvm_tlm_analysis_fifo`) genuinely buffers all 3 requests — `outstanding`
reaches 2. But the generated loop `forever { get(req); <seam>; start_item; finish_item; }` drives
**one** response, then returns to `get()` and blocks forever on a new request that never comes. The
seam can reorder *which* request the one response answers, but it cannot answer *more than one per
incoming request* — and `get`/`start_item`/`finish_item` are generated, not pragma, so no seam
fixes it.

## What this proves — and does not

**Proves [C]:** multi-outstanding OoO is a real capability gap; buffering works but the response
path strands a burst; the naive seam (claimed "expressible" without running it) does not work.

**Does not:** it is not a claim that OoO is *forbidden* — a first-class `respond: pipelined` shape
(a per-ID queue drained by an independent thread, à la `axi_rand_slave`'s `fork … join_none`) would
express it. That feature is scoped in the assessment §3, not built.
