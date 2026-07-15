# T5 probe — the K0 seam holds a chandle + a stepped ISS

Evidence for [`../t5_ibex_cosim_assessment.md`](../t5_ibex_cosim_assessment.md) §1. Settles the
campaign's headline T5 prediction — *"K0 cannot hold a model handle or a step contract"* — by
construction, on Xcelium 25.09.

The stub `cosim_dpi.c` / `cosim_dpi_pkg.sv` stand in for the lowRISC **Spike fork's** real DPI,
whose signatures were verified against source: `chandle spike_cosim_init(string isa, …)` +
`void spike_cosim_release(chandle)` + companion step DPI. This proves *expressibility of the seam*,
not a real lockstep run (that needs the fork — see the assessment's NO-GO).

## Run it

    # 1. generate a minimal bench (predictor imports the cosim DPI package)
    quick-uvm generate -c cosim.yaml -o gen --no-backup       # 23 created

    # 2. paste predictor_paste.sv's two blocks into their pragma regions:
    #    class_item_additional -> gen/cosim_predictor.svh   (holds `chandle cosim_h;`)
    #    prediction_logic      -> gen/cosim_reference_model.svh  (steps the ISS on extr.valid)

    # 3. elaborate with the stub DPI linked
    xrun -uvm -sv cosim_dpi_pkg.sv gen/cosim_if.sv gen/clkgen.sv gen/cosim.sv \
         gen/cosim_tb_pkg.sv gen/tb_top.sv cosim_dpi.c -top tb_top -elaborate
    # -> 0 errors: the K0 predictor holds a chandle and steps a DPI ISS, DPI linked.

## What it proves — and does NOT

**Proves [C]:** a QuickUVM predictor (a stateful `uvm_subscriber` class) can hold a `chandle` in
`class_item_additional`, `import "DPI-C"` a stepped-ISS API, and call it per retired instruction from
`prediction_logic` — valid, DPI-linked, elaborates. The predicted seam-break does not happen.

**Does not prove:** a correct lockstep run against a real ISS (the stub is not Spike), nor that
QuickUVM reproduces the full Ibex cosim *env topology* — the multi-phase monitor, the agent-owned
scoreboard, the `mem_model`, the drain/flush reset — which are real gaps, assessed separately in the
assessment §2.
