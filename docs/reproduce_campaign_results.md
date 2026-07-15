# The reproduce campaign — results (T1–T6)

Six industrial verification environments, chosen because each was **predicted to break** a
different part of QuickUVM. The goal was not to confirm the tool works; it was to find where it
fails against real, taped-out or shipping RTL. Each target has its own assessment
([T1](t1_hmac_assessment.md) · [T2](t2_spi_host_assessment.md) · [T3](t3_tl_agent_assessment.md) ·
[T4](t4_caliptra_sha512_assessment.md) · [T5](t5_ibex_cosim_assessment.md) ·
[T6](t6_axi_outstanding_assessment.md)); this is the synthesis.

## The one-line result

**The predictor seam and the schema are far more expressive than the campaign predicted — five
"it breaks" predictions all dissolved on contact with simulation. The real gaps are one level up:
VIP ownership, emulation partitioning, env topology. The one true *capability* gap it found — a
multi-outstanding out-of-order responder — has since been built and mutation-proved
(`respond: pipelined`, `examples/axi_read/`); the rest are architecture/topology, banked as
findings.**

## What was proven on real RTL (built + mutation-proved on Xcelium)

- **T1 — OpenTitan HMAC.** The K0 reference-model seam holds a stateful, streaming crypto golden
  model over a register bus (a vendored `cryptoc` DPI library). 6/6, coverage-merged.
- **T2 — OpenTitan spi_host (taped-out silicon).** Three features shipped and mutation-proved
  against RTL not written for them: `respond: prefetch` (flip to `on_request` → the device never
  drives a frame), `clock[].source: dut` (the sampled clock, with a fail-closed phantom-clock
  refusal *and* a runtime dead-clock mutation), and per-lane `inouts` (proven in Standard **and**
  Dual — a scalar enable can express neither). All four CPOL/CPHA modes, a clkdiv sweep (2→32,
  divider-independent). Foreign RTL exposed three defects invisible against DUTs I named myself,
  including a clock guard that refused correct benches.
- **T4 — Caliptra SHA512 (HVL half).** Generates clean, elaborates; the NIST-file golden model
  ports into the K0 seam and survives idempotent regeneration.
- **T5 — Ibex.** The K0 predictor holds a `chandle` and steps a DPI ISS per retired instruction —
  elaborates, DPI linked.

## The gaps (all proven, in increasing severity)

- **T3 — VIP ownership.** F2 `layout: packaged` is a genuinely reusable *artefact* but has **no
  ownership model**: two benches cannot share one generated VIP by reference (both regenerate
  byte-identical copies). Stage 0 proved the seam is *achievable* by hand — the gap is that the
  generator won't emit it. Scoped as roadmap **F2'**, deliberately unbuilt.
- **T4 — the HDL/BFM emulation half.** UVMF's `partition_interface_xif` / `tbx` / `` `ifndef XRTL ``
  apparatus exists for Siemens Veloce emulation — an explicit QuickUVM non-goal. **Gap by design**,
  ~69% of UVMF's hand-written lines.
- **T5 — env topology.** No first-class support for a multi-phase monitor, an agent-owned
  scoreboard, an agent-owned `mem_model`, or reset-as-drain/flush. Each hand-workable in a pragma;
  none first-class.
- **T2 (cleanup) — RAL on a pipelined-read bus.** `register_model:` *integrates* (reg block,
  adapter, predictor, CSR tests all generate and run), but a registered-read register bus delivers
  stale read values through the generic monitor+adapter path — it needs a custom `uvm_reg_frontdoor`,
  the same conclusion the real `spi/quickuvm_tb` reached.
- **T6 — the multi-outstanding, out-of-order responder. The one true *capability* gap — now CLOSED.**
  A QuickUVM responder can *buffer* N outstanding requests, but the `on_request` loop (`forever { get;
  <seam>; finish_item }`) answers one per incoming request and strands the rest. The fix,
  `respond: pipelined` + `reorder_by:`, forks an accept thread (buffers into per-ID queues) and a
  drive thread (drains them without blocking on the bus), plus a `STRANDED_REQUESTS` liveness guard.
  Built and mutation-proved on Xcelium (`examples/axi_read/`: issue `[4 3 2 1 0]` → recv `[4 0 1 2 3]`,
  5/5, break the drain and STRANDED_REQUESTS fires). The full 5-channel AXI VIP remains gap-by-design.

## The meta-lesson: predicted seam-breaks kept dissolving — until running caught one going the other way

**Five confident "it breaks" predictions were wrong**, every time discovered by *generating and
simulating* rather than reasoning:

1. "K0 breaks on a streaming stateful crypto model" (T1) — wrong.
2. "K0's DPI can't hold a library" (T1) — wrong (kept `language: sv` + own import).
3. "CPOL=1 misaligns the monitor prologue" (T2) — wrong (already fixed for observed clocks).
4. "The schema can't express the UVMF SHA512 bench" (T4) — wrong on 4 of 6 predicted items.
5. "K0 can't hold a chandle / step contract" (T5) — wrong (elaborates, DPI linked).

Common cause: **the predictor is a stateful class, so "call a function per transaction" generalizes
to "hold a handle / read a file / step an ISS per transaction."** The seam is far more general than
a per-transaction pure function.

**Then T6 inverted the lesson.** A scoping pass claimed the multi-outstanding responder was
*"expressible today, proven by construction"* — it filled the seams and confirmed **regeneration
survives**, but never simulated it. Running it showed the burst strands. So the same discipline that
refuted five *over-pessimistic* predictions caught an *over-optimistic* one. **The rule this campaign
earned, in full: generation-checking is not simulation. Test expressibility by generating *and
running*, not by predicting and not by regenerating — the paper never settles it, in either
direction.**

## The discipline that made the findings trustworthy

- **Mutation-proof before claiming.** A passing bench proves nothing until it can fail; the
  silent-pass trap fired ~10× across the campaign (a dead responder passing 34/34; a stale snapshot
  passing 8/8; a scoreboard "passing" 2622 idle beats). Every green claim carries a mutation.
- **Adversarial review of the write-ups.** The T2 assessment's first draft had **nine false claims**
  that read fine; a refutation panel that *ran the code* caught them, including a "mutation-proved"
  claim for a feature never mutated. That correction produced the campaign's strongest single result
  (per-lane `_oe`, finally proven). Review-by-reading was worthless; review-by-running was decisive.
- **Demote flattering metrics.** T4's LOC ratio was made honest and then explicitly *not* used as a
  headline; T6 reports no metric at all (`axi_rand_slave` is plain SV, not a generator).
- **Every claim tagged [C]/[I]/[P]** (T3–T6), so a reviewer can audit each at a glance.

## Built since (the one capability gap)

- **T6 `respond: pipelined`** — DONE. The per-ID-queue responder shape, built and mutation-proved
  (`examples/axi_read/`). The campaign's one true capability gap is closed; see the T6 assessment §7.

## Left open (deliberately)

- **T3 F2' (VIP ownership build)** — scoped, seam proven achievable, ~5–7d, not built.
- **T2 RAL custom frontdoor** — the pipelined-read wall; `register_model.frontdoor:` exists for it.
- **T5 full cosim** — NO-GO (needs the lowRISC Spike fork; the one axis is already answered).
- **T2 multi-byte (LEN>1 / CSAAT)** — declined as low-value on an already-thoroughly-proven bench.
