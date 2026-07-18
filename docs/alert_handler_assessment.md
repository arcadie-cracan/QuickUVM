# alert_handler — where "generate flat + fill seams" hits its ceiling (a probe)

**Target:** OpenTitan `alert_handler` DV environment (the security-alert aggregator).
**Kind:** a *probe* — map the env onto QuickUVM, find the wall, bank the finding. **Not built,
not run** (§Threats). This is the first scout-slate target that **confirms** a hard gap: the
[AHB registered-read](../examples/ahb_regs/) and [CDC cross-domain](../examples/cdc_fifo/)
targets each *refuted* their "needs a feature / breaks" prediction; this one does not.

Every claim is tagged **[C]** expressible today (grounded on a green committed example),
**[P]** possible only as hand-written seam glue (no first-class shape), or **[I]** a genuine
capability gap (proven by schema inspection — you cannot run a feature that does not exist).

## The one-line result

The alert_handler does not break because its *signals* can't be modelled — nearly all of them
can, via seams the [fairness rule](reproduce_campaign.md) already permits. It breaks because the
three things that make it *this* block — a **hybrid alert-sender** (spontaneous + reactive in one
agent), a **cycle-accurate escalation reference model** (the block's whole purpose), and a
**write-once agent instantiated ~63× into one DUT** — are each outside what the generator can
carry. QuickUVM would emit the boilerplate and almost none of the hard part. That is a
leverage-collapse + reuse-architecture + cycle-accurate-checking gap, **not** a can't-express gap.

## What the block actually is (verified from source)

Grounded in `hw/ip/prim/rtl/{prim_alert_pkg,prim_esc_pkg,prim_alert_sender,prim_alert_receiver,
prim_esc_sender,prim_esc_receiver}.sv`, `hw/dv/sv/alert_esc_agent/`, and
`hw/ip_templates/alert_handler/dv/env/alert_handler_scoreboard.sv.tpl` (lowRISC/opentitan), plus
the [Theory of Operation](https://opentitan.org/book/hw/top_earlgrey/ip_autogen/alert_handler/doc/theory_of_operation.html):

- **Alert channel** (`prim_alert_sender`/`_receiver`), differential + async-capable:
  `alert_tx = {alert_p, alert_n}` (sender→receiver); `alert_rx = {ping_p, ping_n, ack_p, ack_n}`
  (receiver→sender). An alert is a **four-phase handshake** (`alert`↔`ack`), pulse-shaped. A
  **ping** is a toggle on `ping_p/n`; the sender must answer with a full handshake, and a
  missing/late response becomes a **local alert** (timeout enforced *inside* the handler). A
  differential mismatch (`alert_p == alert_n`) raises `integ_fail`. `AsyncOn[i]` per alert.
- **Escalation channel** (`prim_esc_sender`/`_receiver`), differential, **synchronous-only**:
  `esc_tx = {esc_p, esc_n}` (handler→receiver); `esc_rx = {resp_p, resp_n}`. Escalation is a
  **level** signal held high (≥2 cycles); a ping is a single-cycle pulse on the same lines. The
  receiver responds by **continuously toggling `resp_p/n`** (a "1010" sequence). On a broken link
  the receiver **fail-secure escalates on its own** (`esc_req_o`).
- **Escalation FSM:** 4 classes (A/B/C/D), each a saturating **accumulator vs a shadowed
  threshold**; on trigger, a **4-phase** escalation with a **programmable cycle-count timer per
  phase** (`CLASSx_PHASE0..3_CYC`) drives **4 escalation signals**. Plus 7 local alerts, an LFSR
  ping timer (`PING_TIMEOUT_CYC`), and a crashdump.
- **DV env:** one **reusable** agent — `alert_esc_agent`, selected by `is_alert` × `if_mode`
  (Host/Device) × `is_async` — instantiated **`NUM_ALERTS` (~63) times as alert-senders** and
  **4 times as esc-receivers**, plus the `cip_lib` `tl_agent`. The **scoreboard *is* the
  reference model** (~1000 lines): cycle-accurate accumulators + escalation FSM + phase timers +
  ping timer + interrupt-timeout path + crashdump, checked with `wait_n_clks` / `DV_CHECK_EQ`.
- **Clocks:** the block-level DV TB binds every alert/esc interface to the **main clock** (async
  is emulated by `is_async` in the agent, not a separate physical domain); the only second
  physical domain is EDN. So ~2 domains, not one-per-alert.

## The mapping, mechanism by mechanism

| # | alert_handler mechanism | QuickUVM | Grounding |
|---|---|---|---|
| 1 | Dual-rail signals as pairs of 1-bit ports | **[C]** | any multi-port agent; `inouts` (i2c) |
| 2 | Differential-integrity check (`p == n` → fail) | **[P]** | a K1 SVA seam; no `diff:` type |
| 3 | 4-phase alert / esc handshake protocol | **[P]** | driver/responder seam (protocol glue) |
| 4 | Async alert crossing (CDC) | **[C]** | M1 + `cdc_fifo` (in-order CDC proven) |
| 5 | esc-receiver = continuous toggle response | **[C]** | continuous responder (`memslave`) |
| 6 | Alert accumulators + escalation FSM **state** | **[C]** | K0 predictor holds state |
| 7 | **Hybrid alert-sender** (spontaneous + ping-reply) | **[I]** | `mode` is initiator XOR responder |
| 8 | **Cycle-accurate phase / ping timers** | **[I]** | `predict(txn)→txn`, no clock handle |
| 9 | **1 agent × ~63 instances into 1 DUT** | **[I]** | C3 `instances` = per-instance DUT |
| 10 | tl_agent CSR access (RAL) | **[C]** | `regfile`/`ahb_regs` (mod. TL-UL VIP) |

The three **[I]** rows are the finding; the rest is context.

### [I]-7 — the hybrid alert-sender has no first-class shape

An alert-sender does two unrelated things: it **spontaneously raises alerts** (a peripheral event,
no incoming request) *and* it **answers pings** (a reaction to a DUT toggle). QuickUVM's
`mode: Literal["initiator", "responder"]` is exclusive (`quick_uvm/models.py`): an initiator drives
stimulus but has no request→response machinery; a responder's forever-sequence blocks on observed
requests and cannot self-initiate. The OpenTitan agent is `dv_reactive_agent`-derived and does both
because reactivity is a *second* monitor-fifo + responder sequence layered on an initiator — a
structure QuickUVM deliberately keeps as an either/or ([the reactive-agent investigation](reactive_agent_investigation.md)).
**[P] workaround:** an initiator agent that raises alerts, with the ping-response hand-forked in the
driver seam — but that is bespoke protocol glue, not a shape the generator carries (not constructed
here — flagged).

### [I]-8 — the cycle-accurate ref-model lives outside the transaction predictor

The escalation timers *are* the alert_handler's job: phase *k* must last **exactly**
`CLASSx_PHASEk_CYC` cycles, and a ping must be answered within `PING_TIMEOUT_CYC`. OpenTitan checks
this in the scoreboard with `wait_n_clks` + `DV_CHECK_EQ` — cycle-referenced. QuickUVM's K0 seam is
`predict(sequence_item) → sequence_item` (`sb_reference_model.svh.j2`): it sees **transactions, not
cycles**, and holds **no clock handle**. Duration-exact temporal checking is structurally not a
transaction-level activity. **[P] partial:** a K1 SVA could assert a duration, but the bound is a
*register-programmed* value (shadowed CSR) the assertion would have to read from RAL — awkward, and
still not the predictor's job. The ~1000-line reference model is the bulk of the human effort and
sits almost entirely in territory the generator does not reach.

### [I]-9 — write-once-reuse × ~63 is the known VIP-reuse gap, at scale

The alert_handler env's whole economy is **one** `alert_esc_agent` definition **reused ~67 times**
with per-instance config (`is_alert`/`if_mode`/`is_async`) into **one** DUT. QuickUVM regenerates an
agent per YAML entry; C3 `instances` (`InstanceConfig`) gives each instance its **own** interface
*and DUT* (an 8-bit *and* a 16-bit datapath as separate benches) — the wrong topology for N ports on
one DUT; F2' shares an agent *by reference* but not as an indexed array with per-index config. This
is exactly the "biggest architectural gap — regenerates per bench" already on the roadmap ([T3 VIP
ownership](t3_tl_agent_assessment.md)), made concrete: here the reuse factor is ~67, so the gap
stops being a nicety and becomes the difference between a tractable bench and an untenable one.

## Synthesis

Stack the three **[I]** rows and the picture is consistent with the whole campaign's grain: the
*seams* can express almost any behavior (fairness permits hand-written protocol code), but the
alert_handler asks the generator to carry (a) an agent shape it doesn't have, (b) a cycle-accurate
checker that isn't transaction-level, and (c) a reuse-array topology it regenerates instead of
instantiating. What QuickUVM *would* emit — agent skeletons, interfaces, the package, env wiring, a
RAL adapter — is real but is the boilerplate; the ~4000 lines that matter (the alert_esc VIP
handshake + the ~1000-line escalation reference model) are hand-written in territory the generator
does not reach. The scout's "hard break at the mapping stage" is **confirmed** — and now precisely
located: not can't-express, but *the generator's leverage collapses toward zero on exactly this
block*. This is the honest counterweight to AHB and CDC, where the pessimistic prediction dissolved.

## Threats to validity

- **Not built, not run.** Unlike the AHB and CDC findings (both Xcelium-green, mutation-proved),
  this is a paper mapping. A full build is infeasible (rows 7–9), and a *partial* build would be a
  misleading half-thing. The confidence therefore rests on three legs, each independently checkable:
  1. **OpenTitan facts** — VERIFIED from named source files/docs (cited above), not recalled.
  2. **QuickUVM gaps** — proven by **schema inspection**: `mode` is a two-value `Literal`; the K0
     `predict()` signature takes/returns one transaction with no clock; `InstanceConfig` documents
     per-instance DUT/interface. An absent feature cannot be run; schema is the right proof.
  3. **The [C] rows** — grounded on **existing green committed examples** that actually run
     (`spi_device`, `memslave`, `cdc_fifo`, `dualreg`, `regfile`), not on a fresh generate.
- **[P] rows are un-constructed** — where I say "possible via a seam," I did not write the seam.
  Flagged as [P], not [C], for that reason.
- **Escalation-is-sync / async-is-emulated** corrections are folded in above so the finding does not
  overstate the multi-clock demand (the campaign's demote-flattering-inputs discipline, inverted).
- **TL-UL** is held out of the verdict (a VIP concern), exactly as the campaign's TL-UL→generic
  normalization does — noted, not folded in.

## What this argues for (roadmap)

Nothing new to *build* here — the finding's value is a well-located ceiling. It sharpens the
priority of two items already on the list: **a hybrid (initiator+reactive) agent shape** and the
**reuse-array / shared-VIP** topology. It also names a genuinely new axis — **cycle-accurate
temporal checking** (a clock-referenced checker seam, distinct from the transaction-level K0
predictor) — as the capability a security/escalation block would need first. All three are
architectural, none is a quick win, and the block is a reasonable one to *not* target until they
exist.
