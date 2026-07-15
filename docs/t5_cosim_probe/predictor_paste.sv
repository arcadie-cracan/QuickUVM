=== paste into cosim_predictor.svh, class_item_additional seam ===
  // pragma quickuvm custom class_item_additional begin
  // The ISS model HANDLE — a stateful, DUT-leads lockstep cosim (Ibex/Spike shape). The
  // predictor is a CLASS, so it can hold this across transactions. This is exactly the
  // contract my docs predicted K0 'cannot hold'.
  chandle cosim_h;
  bit     started;
  // pragma quickuvm custom class_item_additional end

=== paste into cosim_reference_model.svh, prediction_logic seam ===
  // pragma quickuvm custom prediction_logic begin
  // STEP the ISS when the DUT retires an instruction (extr.valid). DUT-leads: the model
  // advances on the DUT's event, not the TB's. Predicted expected = the ISS's own result.
  int unsigned iss_rd;
  if (!started) begin cosim_h = cosim_init(); started = 1'b1; end
  if (extr.valid) begin
    void'(cosim_step(cosim_h, extr.pc, extr.insn, iss_rd));
    extr.rd_wdata = iss_rd;
  end
  // pragma quickuvm custom prediction_logic end
