# Reproduce-and-compare campaign — target selection

Which industrial UVM environments should QuickUVM be measured against, and what should
each one be expected to **break**?

**Prior art:** [`maturity_assessment_rv_timer.md`](maturity_assessment_rv_timer.md) —
OpenTitan `rv_timer`, reproduced and Xcelium-green (~873 lines generated, ~42 hand-written).
That settled one thing: a **register block + initiator agent + RAL + CSR suite +
golden-model scoreboard** generates with strong parity. It settled nothing else.

**Selection rule:** every target must be picked for what QuickUVM will **fail** to
reproduce. A target we are confident of passing is a wasted week. Each target's predicted
failure is written down **before** the build, and any prediction that turns out wrong must
be reported as such — a campaign that only confirms its own hypotheses is a marketing
exercise.

**Five targets, not seven.** Four axes get no target on purpose (§3). Padding the list to
fill a matrix is the exact mistake this rule exists to prevent.

---

## 1. Findings that cost zero build days

The survey paid for itself before a single bench was written.

### 1.1 Our own reactive-agent design doc is wrong

[`reactive_agent_investigation.md`](reactive_agent_investigation.md) claimed the reactive
driver "stays UNCHANGED". True for OpenTitan/Verilab; **false for OpenHW OBI and CESNET
OFM**, whose slave drivers are **non-blocking** (`try_next_item()` + a grant task) and
**idle-drive every cycle** — because a slave that drives only when it holds an item leaves
the bus at **X**. Five distinct industrial idioms exist; our `mode:` schema must express at
least the blocking and the non-blocking shapes or it is under-specified. The doc now carries
a correction. **Fix the schema before building the feature.**

### 1.2 `inout` / tri-state / open-drain is entirely unsupported — P0

`PortConfig.direction` is `Literal["input", "output"]`; there is **zero** tristate,
pull-up or open-drain support anywhere in the generator or templates. This blocks I2C and
every bidirectional bus. Found by `grep`, not by a campaign — so **prove it on a small
bidirectional example, not on a 15-day I2C bench**.

### 1.3 A "sampled clock" — a clock the TB observes but never generates

SPI `SCK` and I2C `SCL` are **DUT outputs**. Every QuickUVM clock comes from a generated
`clkgen`; M1 has no concept of a clock domain the testbench merely samples. Rides on T2 for
free.

### 1.4 The fairness calibration that stops us reporting non-gaps as gaps

**No generator on earth generates protocol logic.** OpenTitan's *own* generator
(`util/uvmdvgen/`, Mako) emits `device_driver.sv.tpl` with a **completely empty
`get_and_drive()`** and a `host_driver.sv.tpl` containing literally `// TODO: do the driving
part`. Siemens UVMF hand-writes its AHB protocol inside pragma regions —
`HMAC_in_driver_bfm.sv` is **1,107 lines, all human**.

> Any campaign finding of the form *"QuickUVM could not generate the SPI/I2C/TL-UL protocol
> driver"* is **NOT a gap** and must not be reported as one. The fair test is: *does QuickUVM
> emit the right scaffold, with a correctly-placed pragma hole, in the right component?*

Read `util/uvmdvgen/` and `fvutils/uvmf-full` **before** the campaign starts. This is a
mandatory input, not optional reading.

---

## 2. The shortlist (ranked = run order)

### T1 — OpenTitan **HMAC** + the vendored `cryptoc` DPI-C golden model
*(lowRISC/opentitan · `hw/ip/hmac/{rtl,dv}` · Apache-2.0, **including** the vendored C crypto)*

Earl Grey silicon block; DV env 3,711 LOC; signed off against **NIST test vectors**.

- **The one axis — the reference-model seam's *temporal shape*.** K0 is `predict(item) → exp`:
  one transaction in, one expected out. HMAC's model is **stateful and streaming**: N
  `msg_fifo` bus writes accumulate into a byte queue → a `hash_process` CSR **event** triggers
  a call into a C library → the digest appears across a **multi-register CSR array**, many
  cycles later.
- **Predicted failure.** (1) **K0 breaks** — the predictor seam has no vocabulary for
  accumulate → trigger-on-control-event → compare-later-across-N-registers. (2) **DPI build
  plumbing** — we emit a single `<dut>_reference_model.c`; can we link a **multi-file C
  library**? (3) **RAL register arrays** (`KEY_0..31`, `DIGEST_0..7`) — rv_timer's 5 scalar
  regs never touched this. (4) **No file-driven stimulus** (NIST vector files → sequences).
- **Why first.** The only target QuickUVM can generate **on day one** — a pure, uncontaminated
  measurement. And it attacks a **shipped pillar**: finding that K0 is *item*-shaped where
  industry is *stream*-shaped is far more uncomfortable, and therefore more valuable, than
  re-confirming a gap we already documented. Also de-risks DPI-on-Xcelium, which T5 needs.
- **Effort 5–8 d.** `hmac_core.sv` has **zero TL-UL references** → wrap in a generic reg-file,
  exactly as `examples/rvtimer/rtl/rvtimer.sv` did. Scope to **SHA-256 / HMAC-SHA-256 only**.
- **Bar.** PASS: the *generated* scoreboard survives — accumulate/trigger/multi-register
  compare fits **inside pragma regions**, Xcelium-green on ≥1 NIST vector set + random traffic,
  C library links from a generated filelist. **FAIL (the interesting outcome):** the generated
  predictor must be discarded and hand-written, i.e. K0 is bypassed rather than filled.

### T2 — OpenTitan **spi_host** + `spi_agent` in **Device (reactive)** mode
*(`hw/ip/spi_host/dv/`, `hw/dv/sv/spi_agent/` · Apache-2.0 · Xcelium officially supported)*

- **The one axis — the reactive/responder agent** (our biggest gap). The DUT is the SPI
  *host*, so the TB **must** be a device reacting to DUT-driven SCK/CSB. `spi_host_env_cfg`
  sets `if_mode = Device; has_req_fifo = 1`; `spi_agent extends dv_reactive_agent
  #(.HOST_DRIVER_T(...), .DEVICE_DRIVER_T(...))`; `dv_reactive_agent::connect_phase` wires
  `monitor.req_analysis_port → sequencer.req_analysis_fifo`. This validates our schema against
  **taped-out silicon** rather than against our own sketch.
- **Predicted failure.** (1) **Un-generatable today** — no `mode: responder`; this is a
  *feature build*, not a generation run. (2) **A clock the TB samples but does not generate**
  (§1.3). (3) cip_lib common tests — we will **over-generate** ~2–3k lines OpenTitan inherits.
- **Effort 10–15 d**, of which **4–6 d is the `mode: responder` feature** (a permanent asset).
  Adjacency discount: *this repo is an SPI project with a QuickUVM SPI bench already green on
  Xcelium in all four CPOL/CPHA modes.*
- **Bar.** PASS: a **generated** responder agent, sampling a DUT-sourced SCK, checked by an A2
  two-stream scoreboard, Xcelium-green across all four CPOL/CPHA modes, with hand-written code
  confined to the responder pragma seam and the protocol decode.
- **Circularity warning.** We derived our design *from* `dv_reactive_agent` and now validate it
  *against* `dv_reactive_agent`. Mitigated by §1.1 — the survey already **falsified** part of
  our design using idioms from outside OpenTitan.

### T3 — OpenTitan **`hw/dv/sv/tl_agent`** as a standalone, versioned **shared VIP**
*(2,033 LOC + its own self-test env + a FuseSoC manifest `lowrisc:dv:tl_agent` · Apache-2.0)*

One agent, consumed by ~30 IP benches and the chip bench.

- **The one axis — VIP *ownership*, not VIP *layout*.** Stated as narrowly as possible: *can
  QuickUVM emit a standalone, versioned, bench-independent VIP that a **second** generated
  bench consumes **by reference** rather than by regeneration?* rv_timer never asked this. This
  is the cheapest experiment that settles whether **F2 is real reuse or tidy foldering**.
- **Predicted failure.** A functionally equivalent agent with the **wrong ownership model**: no
  package version/identity; **no way for two benches to depend on one generated agent**; no
  self-test bench for the VIP; and `tl_reg_adapter` lives *inside* the VIP whereas C5 wires RAL
  per-bench. Secondary: `tl_device_driver` is a **multi-outstanding, pipelined responder** —
  exactly the case our own design doc **defers**.
- **Effort 5–7 d** — the smallest. **No DUT bring-up** (`tl_agent/dv` is agent-to-agent).
- **Bar.** PASS: a versioned agent package generated **once**, consumed **by reference** by two
  different generated benches, with its own self-test bench; both Xcelium-green.
- **Caution.** A naive LOC comparison will **flatter** QuickUVM (protocol code is hand-written
  under any methodology). Measure **structure** — files, classes, analysis ports, TLM
  connections, manifest fields — not lines.

### T4 — **Caliptra SHA512**, a **UVMF-generated** bench — *generator vs generator*
*(chipsalliance/caliptra-rtl · `src/sha512/uvmf_sha512/` · Apache-2.0)*

Caliptra is the OCP/CHIPS-Alliance datacenter **silicon root of trust** (AMD, Google,
Microsoft, NVIDIA). Its README states plainly: *"The UVM Framework generation tool was used to
create the baseline UVM testbench for verification of each IP component."*

- **The one axis — schema expressiveness against the incumbent industrial generator.** UVMF is
  *architecturally identical to QuickUVM*: **Python + Jinja2 + YAML + a schema validator +
  regenerate-over-existing-source with `// pragma uvmf custom` code preservation**. Same tool
  class, deployed on taped-out silicon. Their human ratio (**1,087 / 6,238 = 17.4%**) is the
  **same mechanically-countable metric** as our 873-vs-42 — the only apples-to-apples generator
  comparison available anywhere.
- **Predicted failure.** Inexpressible in our schema: the **driver-proxy / HDL-side BFM split**
  and `partition_interface_xif` **emulation partitioning**; an ACTIVE RESPONDER role;
  `hdl_typedefs`; an explicit `tlm_connections:` list (we *infer* connections — is inference
  enough?). **Expected verdict — a publishable boundary statement:** QuickUVM reproduces the
  **HVL half** with strong parity and **structurally cannot reproduce the HDL/BFM half** —
  which exists for Veloce emulation, an explicit QuickUVM non-goal. **Part of the "gap" is gap
  by design**, and this tells us which part.
- **Effort: 2–3 d for the paper slice** (map their YAML → ours; emit the inexpressible list) —
  do it in week 1, it is nearly free and it shapes everything downstream. 8–12 d for the full
  build.
- **Risk.** Xcelium bring-up of the `caliptra_prim` cone is **unverified** (their CI is
  VCS/Verilator). But note: we do **not** need to *run* their bench — the comparison is
  architectural.
- **Bonus to bank:** their predictor shells out to `$system("python test_gen.py")` and
  `$fscanf`s a text file. Porting that to QuickUVM's K0 DPI-C seam is a **QuickUVM win** and
  should be reported as one.

### T5 — lowRISC **Ibex**: the 2-agent subset — **CONDITIONAL**
*(`dv/uvm/core_ibex/common/{ibex_mem_intf_agent,ibex_cosim_agent}` · Apache-2.0 · `xlm` in-tree)*

~1,400 LOC subset of a 9,249-LOC env. **`riscv-dv` explicitly excluded.**

- **The one axis — lockstep-ISS cosimulation as a checker seam:** a `chandle`-held, *stateful*,
  **DUT-leads** model. The scoreboard holds `chandle cosim_handle` and steps Spike **when the
  DUT retires an instruction**. Categorically different from HMAC's "call a pure C function".
- **Predicted failure.** (1) **K0 cannot hold a model *handle* or a *step* contract.**
  (2) **Multi-phase monitor ports** — Ibex emits at the **address phase** *and* the **data
  phase**; our monitor has exactly one `ap`. (3) A **monitor-only agent that owns a
  scoreboard** — no slot in our schema. (4) **Agent-owned `mem_model`**. (5) Reset as a
  **drain/flush contract**, not stimulus.
- **GO/NO-GO GATE (day 1, before any commitment):** build the **lowRISC Spike *fork*** (upstream
  Spike will not do), produce the DPI shared lib, link it under Xcelium. If that does not stand
  up in one day, **kill the target.**
- **Effort 8–13 d.** Highest risk in the set; runs last.

---

## 3. Coverage matrix

**■ = primary** (the target's reason to exist — exactly one per row). **○ = secondary**
(exercised and reported; not why we fund it).

| Target | reactive agent | shared VIP | cosim / ref-model *at scale* | multi-clock / CDC | out-of-order | register cov (V2) | crypto / DPI model | mem model | generator-vs-generator |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **T1** HMAC | — | — | ○ | — | — | ○ | **■** | — | — |
| **T2** spi_host | **■** | ○ | — | ○ *(sampled clock)* | — | ○ | — | ○ | ○ |
| **T3** tl_agent | ○ *(pipelined)* | **■** | — | — | ○ | ○ | — | — | — |
| **T4** Caliptra | ○ | ○ | — | — | — | ○ | ○ | — | **■** |
| **T5** Ibex | ○ | — | **■** | — | ○ | — | — | **○** | — |

Reactive appears in four rows, but **only T2 is funded for it**; the others are idiom
corroboration harvested at zero marginal cost — which is precisely what falsified our design
doc (§1.1).

### The four columns with no primary — why that is the answer, not a hole

- **Multi-clock / CDC — SETTLED.** M1 shipped and is green on `mclk`/`mxclk`/`csoc`. OpenTitan's
  `pwrmgr`/`clkmgr` **do not even instantiate extra clock-domain agents** — their CDC content is
  in RTL and assertions, not DV architecture. The axis is thinner than it looks. The one residual
  sub-gap is the **sampled clock** (§1.3), and T2 hits it free.
- **Out-of-order — HALF-SETTLED.** A2 shipped out-of-order *scoreboarding* (mutation-proved on
  `reqrsp`). The unsettled half is the out-of-order *responder*, which rides on T3 and T5.
  Funding an AXI VIP to re-prove A2 would cost 11k lines.
- **Register coverage (V2) — an agreed roadmap item.** A target whose finding is "V2 is absent"
  re-proves a settled point, exactly like another register block.
- **Mem model — already slice 2 of the responder feature.** Rides on T5 and T2.

---

## 4. Sequenced plan

~30–46 person-days. **The campaign can stop cleanly after any target.**

```
WEEK 1-2   T1  OT HMAC                5-8d   MEASURE   (QuickUVM as shipped — nothing to build first)
   ∥       T4a Caliptra paper slice   2-3d   MEASURE   (YAML→YAML mapping; near-free; shapes everything)
   ∥       [feature] mode: responder  4-6d   BUILD     (fix §1.1 FIRST; independent of T1)
WEEK 3-5   T2  OT spi_host            6-9d   VALIDATE  (consumes the feature above)
WEEK 5-6   T3  OT tl_agent            5-7d   MEASURE   (cheapest; settles "is F2 real reuse?")
WEEK 6-9   T4b Caliptra SHA512 full   8-12d  MEASURE   (Xcelium bring-up = the risk)
WEEK 9+    T5  Ibex subset            8-13d  GATED     (1-day Spike/DPI go/no-go FIRST)
```

**The organising principle, and it should structure the write-up:** separate targets that
**MEASURE QuickUVM as shipped** (T1, T3, T4 — uncontaminated, like rv_timer) from those that
**BUILD-then-VALIDATE** (T2, T5 — a feature must ship before anything can be generated, so they
are feature projects with a validation bench, not measurements).

---

## 5. Fairness normalisations — declare these *before* any numbers

Carried forward from rv_timer:

1. **Bus normalisation** — TL-UL → a generic single-cycle register bus. `hmac_core.sv` and
   `i2c_core.sv` were *verified* to have **zero TL-UL references**, so this is a wrapper, not a
   rewrite. TL-UL's protocol machinery is a VIP concern and an explicit **non-goal**. *Exception:*
   T3 **is** the TL-UL agent — there we measure **structure, not LOC**.
2. **Four LOC buckets, never one number** — (A) human DUT-specific DV, (B) human boilerplate,
   (C) tool-produced skeleton the human fills, (D) machine-carried. Bucket (A) is mechanically
   countable for QuickUVM (grep the pragma regions) — and, uniquely, for **UVMF** too.
3. **Inherit (~6×) vs generate (flat)** — OpenTitan carries ~10k lines of `cip_lib`/`dv_lib` by
   inheritance. Declare it **"library, not generated"** and score it neither for nor against.
   QuickUVM will over-generate several thousand lines OpenTitan inherits: that is the
   architecture, not a defect.

New for this campaign:

4. **No generator generates protocol logic** (§1.4). The bar is *scaffold + correctly-placed
   pragma hole*, not protocol code.
5. **Emulation / HDL-BFM partitioning is a declared NON-GOAL.** Score as "gap by design".
6. **Reproduce ARCHITECTURE + 4–6 representative vseqs, never the full testplan** (OT i2c has 41).
   State the checking scope explicitly — rv_timer's 42-line bucket-(A) *understated* fidelity
   precisely because its checking scope was smaller, and we must not repeat that silently.
7. **We do not need to RUN the reference bench.** The comparison is architectural.

**Threats.** Selection bias toward OpenTitan (3 of 5) — mitigated by T4 (Siemens design school)
and T5, but it must be *stated*. And **the "generator-vs-generator" framing is valid only for
Caliptra**: `uvmdvgen` is CLI-driven, Mako, one-shot, with **no** preservation pragmas — it
*seeds* an env that humans then own for years. For our purposes **OpenTitan is a hand-written
reference**; **only UVMF/Caliptra is a live generator**. A clean 3-way taxonomy worth publishing:

| | config | engine | regeneration |
|---|---|---|---|
| **UVMF** | YAML | Jinja2 | regenerate + merge, pragma regions |
| **uvmdvgen** | CLI flags | Mako | one-shot, no preservation |
| **QuickUVM** | YAML | Jinja2 | regenerate + merge, **fail-closed** pragma preservation |

---

## 6. What we should NOT attempt

**Rejected on merit — they would prove nothing new**

- **Another plain register block** — settled by rv_timer.
- **OT `uart`** — the most tempting ("the classic next block after a timer") and the **least
  informative**: its driver is **initiator-only**, i.e. exactly our existing model, so it
  re-proves rv_timer with a serial wire bolted on. Its one new axis (driver bit-timing derived
  from a CSR-programmed baud divisor) is real but small → **harvest as a roadmap note, do not
  fund a bench.**
- **OT `pattgen`** (output-only passive monitor — already what we generate), **`pwrmgr`/`clkmgr`**
  (re-proves M1).

**Rejected on double-coverage — their unique lesson is harvestable free**

- **OT `i2c`** — a legitimate reactive target, but it double-covers T2 **and** is dead on arrival
  without `inout` support (§1.2). The `inout` gap was found by grep; prove it with a small
  bidirectional example, not a 15-day bench whose other 90% duplicates spi_host.
- **OT `spi_device`** — a 2,817-line scoreboard trap (4 modes + TPM + passthrough → needs *two*
  SPI agents).
- **OpenHW `uvma_obi_memory`** — needs a *stub* OBI master as its DUT, which guts the "industrial
  DUT" claim. (Correction: its "versioned VIP" framing is over-claimed — `ip.yml` is **0 bytes**.
  OpenTitan's FuseSoC `.core` files *are* real manifests, which is why T3 uses `tl_agent`.)

**Rejected — not actually clonable**

- **CV32E40P step-and-compare** — links the **Imperas OVPsim** DPI library (now Synopsys). Not
  redistributable. *(One detail worth a line anyway: in the RVVI agent the **driver drives the
  ISS, not the DUT** — an inversion no generator schema anticipates.)*
- **Caliptra `soc_ifc` / `keyvault` / `pcrvault` / `caliptra_top`** — hard-depend on Siemens
  **Questa QVIP** and **Avery AXI VIP**; both closed, neither runnable on Xcelium.

**Rejected on scale (months, not days)** — OT `flash_ctrl` (17.8k), `otbn`, `usbdev`, `aes`,
`entropy_src`, `kmac`, chip-level DV; the full `core_ibex` env; full CV32E40P/CVA6; `uvma_axi5`
(11.3k). Beyond size: **OpenTitan-ecosystem entanglement** — `sram_ctrl`/`flash_ctrl` import
`otp_ctrl_pkg`, `lc_ctrl_pkg`, `sec_cm_pkg`… so reproducing them measures QuickUVM against
*OpenTitan's security infrastructure*, not against DV.

**Rejected — and this one is a negative finding, not a scoping cut**

- **`riscv-dv`** is itself a UVM environment that **elaborates in order to emit an assembly
  program**. Its output is a `.S` file, not pins. **QuickUVM has no story for instruction-stream
  generation and arguably should not.** Report as an architectural **scope limit**: in CPU DV the
  stimulus is an offline program generator and the UVM sequences only serve memory responses.

**Rejected — lane corrections (claimed to have UVM; do not)**

- **Chips Alliance VeeR EL2** — the *only* UVM in the repo is `testbench/uvm/mem/`: **13 files,
  487 lines**, a toy DCCM test; no cosim anywhere. Genuinely industrial silicon, but its
  verification is **cocotb/pyuvm** — it fails the "real UVM env in-tree" constraint outright.
- **`pulp-platform/axi`** — **not UVM at all** (`package axi_test;` + module-level testbenches;
  zero `uvm_*` hits). Industrial and Bender-versioned, and the *perfect illustration of the
  shared-VIP idea* — with no UVM in it.
- **Accellera / open vendor VIP — does not exist.** Accellera ships the UVM *library*, not
  protocol VIP. Commercial AXI/APB UVM VIP is uniformly closed (confirmed *from inside*
  Caliptra, which references `${QUESTA_MVC_HOME}` and Avery `aaxi`). The only genuinely open,
  genuinely industrial **vendor** UVM asset is **UVMF itself** — and the right move is not to
  reproduce it but to **compete with it**, which is T4.

**Rejected — CESNET OFM (a close call, stated explicitly)**

Genuinely industrial (shipping on Silicom 100G/400G NICs) with a real 30k-line shared UVM VIP.
Rejected because: its flow is **Questa-only** (zero `xcelium|xrun` hits), its **DUT is VHDL**, and
**mixed-language is an explicitly declared non-goal** in our own roadmap — funding a target to
prove a declared non-goal is the definition of wasted budget. Its most valuable gift (the
type-swapped `uvm_driver #(RSP, REQ)` slave idiom that **falsifies our own design doc**) has been
harvested for free. That is the right way to consume this repo.

---

## 7. Free roadmap items — queue these now, no campaign needed

1. **`inout` / tri-state / open-drain port support** — **P0**; blocks I2C and every bidirectional
   bus. Validate on a small bidirectional example.
2. **Fix the `mode:` schema for non-blocking responders** (§1.1) — *before* building the feature.
3. **A "sampled clock" concept** — a clock the TB observes but does not generate.
4. **Read `util/uvmdvgen/` and `fvutils/uvmf-full`** before the campaign starts (§1.4).
5. **UART baud-divisor driver timing** — driver bit-timing as a function of a *register value*
   rather than a clock edge. Small, real; harvested from the rejected `uart` target.
