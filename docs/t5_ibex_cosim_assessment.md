# T5 — lowRISC Ibex cosim — assessment

Ibex's DV env checks the CPU against a **lockstep instruction-set simulator** (a Spike fork): the
scoreboard holds a `chandle` to the ISS and **steps it when the DUT retires an instruction**. My own
roadmap predicted this is *the* case that breaks QuickUVM's K0 predictor seam — "categorically
different from HMAC's call-a-pure-C-function." This target tests that prediction.

Claims tagged **[C]** verified by construction (Xcelium) / **[I]** inspection / **[P]** predicted.
The full running cosim is **not built** — it needs the lowRISC Spike *fork* + a DPI shared library
(the campaign's own day-1 GO/NO-GO gate), an 8–13 day high-risk build. The campaign's *one axis* —
does the K0 seam express a stepped-ISS checker? — is answerable without it, and is answered here.

---

## 1. The headline prediction — REFUTED

**"K0 cannot hold a model handle or a step contract."** It can, and it elaborates on Xcelium.

A generated predictor whose `class_item_additional` seam holds `chandle cosim_h;` and whose
`prediction_logic` seam calls a stepped DPI ISS per retired instruction —

    chandle cosim_h;                                   // in class_item_additional
    if (!started) begin cosim_h = cosim_init(); started = 1; end
    if (extr.valid) begin
      void'(cosim_step(cosim_h, extr.pc, extr.insn, iss_rd));   // step on the DUT's retirement
      extr.rd_wdata = iss_rd;
    end

— **elaborates with 0 errors, DPI linked** ([`t5_cosim_probe/`](t5_cosim_probe/)). The stub
`cosim_init()→chandle` / `cosim_step(chandle,…)` is a faithful simplification of the real Ibex DPI,
whose signatures I verified against source: `chandle spike_cosim_init(string isa, …)` and
`void spike_cosim_release(chandle)`, with stepping via companion DPI. **[C]**

The refutation is the same lesson as T1 and T4: the predictor is a **stateful class**, so "call a
function per transaction" generalizes cleanly to "**step a handle** per transaction," and "DUT-leads"
maps because each retired instruction *is* a transaction on the retirement (RVFI-shaped) interface.
This is the **fifth** "it breaks" prediction this campaign that did not — after "K0 breaks" (T1,
twice), "CPOL=1 misaligns the monitor" (T2), and "the schema can't express it" (T4, 4 of 6). The
pattern is now strong enough to state as a rule: **predicted seam-breaks keep dissolving on contact
with construction; test by generating, not by reasoning.**

**What this does NOT claim:** that QuickUVM reproduces the full ~1,400-LOC Ibex cosim env. It claims
the K0 *seam expresses the chandle+step checker contract* — the specific thing predicted impossible.
The env topology around it is §2.

---

## 2. The env-topology predictions — largely CONFIRMED as gaps (each hand-workable)

The *other* four predictions hold up better than the headline. None is a first-class schema feature;
each is hand-writable inside a pragma (which the campaign's fairness rule permits — protocol/topology
glue is hand-written under any methodology), but QuickUVM has no schema knob for them.

| predicted gap | verdict | evidence |
|---|---|---|
| **Multi-phase monitor** (Ibex emits at address *and* data phase; one `ap`) | **PARTIAL [I]** | the monitor template *does* emit a second `request_ap` — but only in the **responder** shape (`has_request_fifo`), not as a general "N analysis ports for N pipeline phases" knob. A second phase-port is a hand-add in the monitor pragma. |
| **A monitor-only agent that owns a scoreboard** | **CONFIRMED [I]** | scoreboards are declared at the **env** level (`analysis.scoreboards: [{source, monitor}]`), not owned by an agent. No schema for "this passive agent carries its own checker." |
| **Agent-owned `mem_model`** | **CONFIRMED [I]** | no `mem_model` field anywhere in `models.py`. A memory model lives in the agent's `class_item_additional` pragma, hand-written. |
| **Reset as a drain/flush contract** (not stimulus) | **CONFIRMED [I]** | reset is stimulus/gating (`external_reset`, driver reset-gating); there is no "on reset, drain outstanding and flush the model" contract. Hand-written in a pragma. |

So the honest split: **the loudest prediction (the K0/ISS seam) was wrong; the quieter
env-topology predictions were right.** QuickUVM expresses the *checker seam* but has no first-class
support for Ibex's *agent/scoreboard/reset topology* — those are pragma-level hand-work.

---

## 3. GO / NO-GO on the full build — NO-GO, honestly

The campaign set a day-1 kill gate: stand up the lowRISC Spike fork + DPI lib under Xcelium in one
day, or kill the target. I did not attempt it, and recommend **NO-GO**, for reasons that are about
value, not difficulty:

- The campaign's **one axis** — does the K0 seam express a stepped-ISS checker — is **already
  answered [C]** (§1), without the fork.
- The remaining work (the Spike fork toolchain, the DPI lib, the multi-phase monitor + agent-owned
  scoreboard + mem_model topology) is 8–13 days that would mostly reproduce **topology glue** the
  fairness rule already treats as hand-written — buying little the seam proof does not.
- It is the highest-risk target in the set (an out-of-tree ISS fork under a simulator its CI does not
  use), and its payoff is a topology reproduction, not a new capability finding.

**The finding is banked** (like T3/T4): the seam question is settled by construction; the env
topology is an inspected gap list; the full cosim is left as a scoped, gated, deliberately-unbuilt
item.

---

## 4. Honest limits

- **Elaboration, not a run.** §1 proves the chandle+step predictor is **valid, DPI-linked SV in the
  seam** (the expressibility bar, same as T4). It does not run a real ISS — the stub `cosim_step`
  is not Spike; a true lockstep run needs the fork.
- **A simplified interface.** The probe uses an RVFI-shaped single-`ap` retirement interface, where
  each retirement is naturally one transaction. Real Ibex has the multi-phase memory interface of
  §2 — which is exactly why §2's gaps are real and stated separately from §1's refutation.
- **`models.py` inspection for §2** is [I], not construction — but each is a plain absence (no
  `mem_model`, no agent-scoreboard, no drain-reset field), the same kind of absence audit used in T3.
