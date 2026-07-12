# Reactive / responder agent — industry investigation

A survey of how UVM environments build a **reactive** agent — one whose driver
responds to DUT-initiated activity (a device/slave/target) instead of proactively
initiating transfers — and the design shape recommended for a future QuickUVM
reactive-agent feature. This is the design rationale for a not-yet-scheduled phase;
it is the reactive-agent companion to
[`whitebox_observation_investigation.md`](whitebox_observation_investigation.md) (K2)
and follows up the architectural gap flagged by
[`maturity_assessment_rv_timer.md`](maturity_assessment_rv_timer.md) and
[`comparison.md`](comparison.md) ("no reactive/responder (device) agent").

> **Status:** analysis only — no code. QuickUVM's agent is **initiator-only** today
> (the driver proactively drives DUT inputs from a sequence). This doc scopes what a
> reactive agent is, how the industry builds one, QuickUVM's exact gap, and a
> minimal opt-in design that stays byte-identical when unused.

## The gap in one paragraph

QuickUVM's driver is a proactive pull-driver:
[`agent_driver.svh.j2:21-31`](../quick_uvm/templates/agent_driver.svh.j2) does
`get_next_item(tr) → drive_item(tr) → item_done()`, driving `vif.cb1.<input_port>`
from a test sequence. A **reactive** agent instead waits for the DUT to initiate a
transfer and drives a *computed response*. The pleasant surprise from the survey:
in the recommended architecture the **driver does not change at all** — the reactive
behavior lives in the sequence, the monitor, and the sequencer. QuickUVM already has
the load-bearing pieces (that exact driver loop, the `input_ports`/`output_ports`
direction split, a passive monitor, flat config distribution); the gap is a handful
of small, opt-in additions.

> ## ⚠ CORRECTION (2026-07-12) — "the driver stays unchanged" is only *sometimes* true
>
> This document originally claimed, as its headline finding, that a reactive agent leaves
> the **driver unchanged**. A follow-up survey of five industrial codebases
> ([`reproduce_campaign.md`](reproduce_campaign.md)) shows that is **true for the
> OpenTitan/Verilab school and false for at least two others**:
>
> | Codebase | Responder idiom | Driver unchanged? |
> |---|---|---|
> | OpenTitan `dv_reactive_agent` / Verilab SNUG-2016 | monitor req-port → sequencer FIFO → forever responder seq; `HOST_DRIVER_T`/`DEVICE_DRIVER_T` swapped at build | **yes** |
> | OpenTitan `i2c_driver` | one driver, `case (cfg.if_mode)` → `drive_host_item` / `drive_device_item` | no (dispatch) |
> | OpenHW `uvma_obi_memory_drv` | master: blocking `get_next_item()`; **slave: non-blocking `try_next_item()` + a separate grant task** | **NO** |
> | CESNET OFM `uvm_mi` | **`uvm_driver #(RSP, REQ)` — REQ/RSP types SWAPPED**; `try_next_item`; `item_done(rsp)` returns the observed request upward | **NO** |
> | Siemens UVMF | polarity-inverting RESPONDER role + a `respond_and_wait_for_next_transfer()` BFM task | n/a (BFM) |
>
> **Why the physics forces this.** A blocking `get_next_item()` driver only drives when it
> *has* an item. For a slave, that leaves the bus **at X between transactions** — fine for a
> master (which owns the bus and is idle by definition), fatal for a slave whose outputs are
> continuously sampled. So a slave driver on a bus with a per-cycle grant/ready obligation
> must be **non-blocking and idle-drive every cycle** (`try_next_item()` + drive-idle-on-miss),
> which is a genuinely different driver loop — not the same one.
>
> **Consequence for the design below.** The proposed `mode: initiator | responder` schema is
> **under-specified**: it must distinguish the *blocking* responder (OpenTitan/Verilab — the
> shape this doc describes) from the *non-blocking, idle-driving* responder (OBI/CESNET). The
> §"Recommended design shape" section is correct **only for the blocking shape**. Settle this
> before implementing. Everything else below (the monitor request port, the sequencer TLM
> FIFO, the forever responder sequence, the response-logic pragma seam, byte-identity) stands.

## Terminology

Four near-synonyms across two **orthogonal** axes — pinning them down decides the
schema keyword:

| Axis | Values | Meaning |
|---|---|---|
| **Behavior** | proactive ↔ **reactive** | who initiates the transfer: the TB, or the DUT |
| **Protocol role** | master ↔ **slave** / device / target / subordinate | bus vocabulary per protocol family |
| **Mode** | active ↔ passive | does the component drive pins at all |

The load-bearing point: **reactive is NOT passive.** A reactive slave is
`is_active == UVM_ACTIVE` — it drives response pins — it simply does so in reaction
to the DUT rather than from a test sequence (Verilab: "a reactive slave … drives
response signals only when a transfer is initiated on its interface by the DUT
master. It is an ACTIVE component"). Any QuickUVM knob must therefore be orthogonal
to the existing `active` flag.

Tool conventions: Verilab says *reactive slave* (+ *responder*); OpenTitan uses
`if_mode = Host | Device`; Siemens UVMF uses `INITIATOR | RESPONDER`; the UVM
Cookbook says *responder*; AXI/I2C say *subordinate*/*target*. **Recommendation:**
use **`reactive`** for the behavioral config knob (protocol-neutral, matches the
dominant literature) and **`responder`** for the role/sequence name (matches UVMF +
Cookbook, avoids master/slave). Device/target/slave/subordinate stay doc synonyms.

## The canonical architecture (Verilab / OpenTitan)

Litterick & Montesano, *"Mastering Reactive Slaves in UVM"* (Verilab, SNUG 2016), is
the definitive treatment, and OpenTitan's `dv_reactive_agent` implements the same
shape. Its central insight: **a reactive slave is structurally identical to a
proactive master agent** (active sequencer + driver + passive monitor) with exactly
three additions and **zero driver changes**:

1. **The monitor publishes the request early.** A *second* analysis port
   (`request_ap`, a partial/request-phase transaction) alongside the usual
   full-transaction port. It `write()`s the request the moment it is decoded. The
   monitor already decodes the protocol for passive mode, so there is **no duplicated
   decode logic** — the whole argument for this architecture.
2. **The sequencer gains a blocking rendezvous.** A `uvm_analysis_export` feeding a
   `uvm_tlm_analysis_fifo`, connected in `connect_phase`. The FIFO exists only to
   give a sequence a *blocking* `get()` — it is a handshake, not a backlog buffer.
3. **A "forever" responder sequence** — set as the sequencer's `main_phase`
   default_sequence (self-starts, raises **no objections**), holding a
   `p_sequencer`:

   ```
   forever begin
     p_sequencer.request_fifo.get(req);   // blocks until the DUT issues a request
     rsp = compute_response(req);         // <-- USER SEAM: reads a mem / protocol model
     start_item(rsp); finish_item(rsp);   // hands rsp to the driver
   end
   ```

4. **The driver is unchanged** — byte-for-byte the proactive
   `get_next_item(rsp) → drive → item_done()` loop. It blocks on `get_next_item`
   until the responder sequence supplies a response; it **never** samples the request
   line. `drive_item` just drives the *response* ports instead of the *request* ports.

**Causality lives in the sequence, not the driver.** Flow per transaction: DUT
drives request → monitor decodes and `request_ap.write(req)` → sequencer FIFO →
responder sequence's `get()` unblocks → computes `rsp` → `start_item/finish_item` →
driver's `get_next_item(rsp)` returns → driver drives the response pins.

**Clocking directions** are the mirror of a master and are the *same direction model
QuickUVM already has*: the slave samples the DUT's request signals (`input` in the
clocking block, read by the monitor) and drives the response signals (`output`,
driven by the driver). Only which set the driver drives (outputs, not inputs) and
the monitor's request-publish timing change.

### The tempting alternative — and why it's rejected

The intuitive design makes the **driver** sample the DUT request and compute the
response itself (a dummy `get_next_item` first, then decode-and-drive). Verilab
explicitly rejects it (their Fig 7/8): it **duplicates the protocol decode the
monitor must already do**, and is "less logical, more error-prone and harder to
maintain." A generator must not bake this in as the default. (Two independent
local-exploration passes reached for exactly this shape — it is the natural-looking
trap, which is precisely why it is called out here.)

For genuinely trivial single-response slaves, Verilab tolerates a pure-BFM shortcut
(driver auto-responds, no sequence). That maps to QuickUVM's "simple by default":
offer the shortcut as the trivial default and the full sequence-based path as the
"powerful when needed" tier — but keep the *decode* in the monitor either way.

### `put_response` / `get_response` — don't confuse the channels

The built-in `uvm_driver #(REQ,RSP)` rsp channel (`item_done(rsp)` →
`get_response(rsp)`, correlated by `set_id_info`) is the **initiator** direction
(driver telling *its* sequence what the DUT answered). The reactive-slave direction
is the opposite: the *sequence* produces the response, the *driver* consumes it via
`get_next_item`. The request travels monitor→FIFO, not via the rsp channel. QuickUVM's
current `item_done()` (no argument) is correct for the common case; `get_response` is
needed on the slave side only when the sequence must observe completion (pipelined /
out-of-order responders).

## Industry practice — two orthogonal knobs

OpenTitan is the clearest reference and proves the two mechanisms are **independent
and composable**:

- **Knob A — a mode flag selects the driver.** `dv_base_agent_cfg` carries
  `if_mode_e if_mode` (`Host | Device`); `dv_base_agent.build_phase` does
  `driver = (if_mode==Host) ? HOST_DRIVER : DEVICE_DRIVER`. Same monitor, sequencer,
  cfg, and wiring — only the driver subclass differs, chosen at **create time** (not
  an `if` inside `run_phase`, so the unused mode generates no dead code). UVMF does
  the analogous thing with an `INITIATOR | RESPONDER` role in YAML.
- **Knob B — the reactive back-channel.** `dv_reactive_agent` is a *subclass* that
  adds `monitor.req_analysis_port.connect(sequencer.req_analysis_fifo.analysis_export)`,
  gated by `cfg.has_req_fifo`. This is the monitor→FIFO→forever-sequence wiring above.

Non-obvious corroboration: OpenTitan's *device drivers*
(`tl_device_driver.d_channel_thread`, `i2c_driver.drive_device_item`) still pull
items with `seq_item_port.get_next_item(rsp)` and return via `put_response(rsp)` —
they do **not** read the monitor FIFO themselves. The back-channel is consumed by the
forever *sequence*. So "reactive" is split across sequence + monitor + sequencer, and
the driver stays a normal pull-driver — exactly Verilab's shape.

**The user's response logic lives in the sequence, never the driver.** OpenTitan's
`tl_device_seq` clones the request, calls `mem.write_byte`/`read_byte` on a standalone
`mem_model` (a `uvm_object` with a sparse `logic[7:0] system_memory[addr_t]` +
read/write/compare/init), randomizes delays/errors, then `start_item/finish_item`. The
`mem_model` is a shareable primitive handed in via config_db. Verilab uses the same
pattern via a `my_storage` component (written+init'd by the monitor so it stays live
in passive mode, read by the sequence).

UVMF folds get-request + drive-response into one responder-BFM task,
`respond_and_wait_for_next_transfer(...)` (2022.1+, deprecating the old `response_info`
YAML), but the response *values* still originate in the responder sequence. The VA
Cookbook "Slave Sequences (Responders)" is the same idea: `rsp = req.copy()`; driver
`get_next_item` then responds; the generating sequence uses `get_response`.

## QuickUVM's current architecture & the exact gap

| Piece | Current (initiator-only) | Reactive needs |
|---|---|---|
| Driver | [`agent_driver.svh.j2:21-31`](../quick_uvm/templates/agent_driver.svh.j2) — `get_next_item/drive_item/item_done`, drives `input_ports` | **unchanged loop**; `drive_item` drives `output_ports` under a gated branch |
| Sequence | [`agent_sequence.svh.j2:19-38`](../quick_uvm/templates/agent_sequence.svh.j2) — proactive `repeat(N) do_item` | a *forever* `get(req) → compute → start/finish_item` responder body |
| Monitor | [`agent_monitor.svh.j2`](../quick_uvm/templates/agent_monitor.svh.j2) — single `ap`, `emit_when` qualifier | a **second** `request_ap` + early request publish (reuse `emit_when`/`request_valid`) |
| Sequencer | plain `uvm_sequencer` | a gated `uvm_analysis_export` + `uvm_tlm_analysis_fifo` + connect |
| Interface | [`agent_if.sv.j2:26-41`](../quick_uvm/templates/agent_if.sv.j2) — `input <dut_out>`, `output <dut_in>` | **direction model reused as-is**; timing becomes reactive |
| Config | `AgentConfig` — `active`, `ports`, `emit_when`, `clock/reset`, `assertions` ([`models.py:640`](../quick_uvm/models.py)) | a `mode`/`reactive` flag + a `request_valid` port |

The precise gap: QuickUVM has the driver loop, the port-direction split, the passive
monitor, and the config-distribution machinery. It lacks (a) the per-agent
reactive/mode flag, (b) the monitor's second request port, (c) the sequencer FIFO +
wiring, (d) a forever responder-sequence template with a response-computation seam,
and (e) the `is_active`-gated connect. Four are small; the responder sequence + its
user seam is the substantive new artifact.

## Recommended design shape

### Schema (minimal, opt-in, byte-identical when unused)

Add to `AgentConfig`, defaulting to today's behavior:

- `mode: Literal["initiator", "responder"] = "initiator"` — the behavioral knob.
- `request_valid: str | None = None` — which input port signals "a request arrived"
  (same semantics as `emit_when`; reuse that machinery). Required for a responder.

No new *ports*: reuse `input_ports` = request (sampled) and `output_ports` = response
(driven). The initiator/responder distinction is **semantic**, not structural — the
direction model is already there.

**Fail-closed validation** (house rule): `mode=="responder"` ⇒ `active==True`, ⇒ ≥1
output port (something to drive as a response), ⇒ `request_valid` names a 1-bit input
port, ⇒ a responder default_sequence exists. Reject `request_valid` on an initiator.
Error at generation time rather than emit a bench that hangs.

### Generation — follow Verilab/OpenTitan, not the driver-computes shortcut

- **Driver:** keep the shared template; under `{% if agent.mode == 'responder' %}`,
  `drive_item` drives `output_ports`. The `get_next_item/item_done` loop is unchanged
  — the load-bearing simplification. Prefer a gated branch over a whole new
  `reactive_driver.svh.j2` (matches the initiator byte-for-byte when off).
- **Monitor:** add a gated second `request_ap` + an early request-publish `write()`,
  reusing `request_valid`/`emit_when` to decide *when* the request is decoded.
- **Sequencer:** gated `uvm_analysis_export` + `uvm_tlm_analysis_fifo` + connect.
- **Responder sequence:** the new artifact — a forever
  `p_sequencer.request_fifo.get(req)` → compute → `start_item/finish_item` body, set
  as `main_phase` default_sequence via config_db (self-starts, no objections).
- **Agent connect:** `is_active`-gated
  `monitor.request_ap.connect(sequencer.request_export)`.

### The response-computation seam (the most important decision)

Put the user's response logic in the **responder sequence**, in a pragma-preserved
region — **not** in the driver. Two tiers, matching "simple by default, powerful when
needed":

1. **Simple default:** a `// pragma quickuvm custom response_logic begin/end` region
   in the responder sequence, defaulting to an echo / constant-ACK (the BFM shortcut
   Verilab tolerates for trivial slaves).
2. **Powerful path:** an optional standalone `mem_model.sv` library primitive
   (`uvm_object`, sparse assoc array, `read_byte`/`write_byte`/`compare`/`init`)
   handed in via config_db and read by the sequence — OpenTitan's exact pattern.
   **Defer this to a second slice.**

### Byte-identity & feature interaction

- **Byte-identity:** every seam gated on `{% if agent.mode == 'responder' %}`; `mode`
  defaults to `"initiator"`. Existing configs render zero new lines → covered by the
  existing example byte-identity gate, exactly as K2 (probes) was.
- **A2 scoreboard:** a reactive agent is a *natural* two-stream fit — initiator =
  source (predict), responder's driven output = actual. Clean.
- **is_active:** orthogonal — `active` = drive-or-not, `mode` = proactive-or-reactive.
  A passive slave is an `active=false` monitor that still decodes (the request port
  tolerates zero subscribers).
- **C2 vseq:** virtual sequences start on initiators only; responders self-run.
- **C3 / M1 / K1 / H1:** parameterization, clock/reset domains, in-interface SVA, and
  subenv composition all compose unchanged (a responder resolves its clock/reset the
  same way as any active agent).

## Effort, risks, and what to defer

**Effort:** medium — larger than K1 (SVA scaffold), comparable to or a little under K2
(probes). The driver reuse and the existing port-direction split remove the hardest
parts. New artifacts: one config field + validation, a gated monitor/sequencer branch
each, one responder-sequence template, one connect line, and an example bench (a
memory-slave or a simple req/rsp device) proven Xcelium-green with a mutation proof —
matching the K2 delivery bar.

**Risks / footguns to design against:**

- The forever responder sequence must **never raise objections** and must always
  respond — the classic reactive-slave failure is stalling the DUT or blocking
  end-of-test.
- The monitor must publish the request **early** (a partial transaction), or the
  response arrives too late. This couples monitor timing to response latency.
- **Do not ship the driver-computes-the-response design** — it duplicates decode and
  is the discouraged path (tempting because it looks like a plain master).

**Deferred (first slice omits):**

- the shareable `mem_model` primitive (slice 2);
- pipelined / out-of-order responders (multiple outstanding requests → needs
  `put_response`/`set_id_info` — materially harder);
- DPI-C response models (SV-only first);
- an OpenTitan-style `if_mode` create-time driver *swap* as a second orthogonal knob
  (only needed if one agent must serve both host and device roles in one bench).

**Recommended first slice:** the single-outstanding, sequence-based reactive
responder with an echo/constant default + a pragma seam, proven on a memory-slave
example. That is the 80% case, honors "simple by default," and lands as one reviewable
slice.

## Sources

- Litterick & Montesano, *"Mastering Reactive Slaves in UVM"*, Verilab / SNUG 2016 —
  the recommended architecture (monitor request port + sequencer `uvm_tlm_analysis_fifo`
  + forever responder sequence + unchanged driver), the rejected driver-decodes
  alternative, the `my_storage` write/read/init pattern, and the reactive-vs-passive
  terminology.
- OpenTitan / lowRISC DV: `dv_base_agent` (`if_mode` Host/Device driver swap),
  `dv_reactive_agent` (`has_req_fifo` monitor→sequencer connect), `tl_device_driver` /
  `tl_device_seq`, `i2c_driver` device path, `mem_model` (sparse memory primitive);
  issue "Device-mode (reactive) UVM agents".
- Siemens UVMF — INITIATOR/RESPONDER interface role; the 2022.1
  `respond_and_wait_for_next_transfer(...)` responder-BFM seam.
- Verification Academy UVM Cookbook — "Slave Sequences (Responders)".
- Accellera UVM 1.2 reference — `uvm_driver #(REQ,RSP)`, `item_done(rsp)` /
  `put_response` / `get_response` / `set_id_info`.
- QuickUVM templates inspected: `agent_driver.svh.j2`, `agent_monitor.svh.j2`,
  `agent_sequence.svh.j2`, `agent_if.sv.j2`, `agent_agent.svh.j2`, `models.py`
  (`AgentConfig`), `generator.py`.
