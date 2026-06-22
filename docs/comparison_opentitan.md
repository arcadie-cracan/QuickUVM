# QuickUVM vs. a mature industrial bench (OpenTitan `rv_timer`)

A **structural gap analysis**: QuickUVM's generated output mapped component-by-component
against a real, industrial-grade, open-source UVM environment — OpenTitan's `rv_timer`
DV — to find where the generator's coverage of a production bench is solid and where it
is genuinely missing capability.

> Companion to [`comparison.md`](comparison.md) (QuickUVM vs. other *generators*). This
> doc compares QuickUVM vs. an industrial *DUT verification environment*. See
> [`parity_roadmap.md`](parity_roadmap.md) for the items this surfaced (C5, V2, R1).

## Why `rv_timer`

Criteria: a **block-level IP with a register file + a data interface** (QuickUVM's sweet
spot), with a **mature, industrial-grade UVM env** (custom-framework UVM accepted), open
source. The survey shortlist:

| Candidate | Framework | License | Note |
|---|---|---|---|
| **OpenTitan** blocks (`rv_timer`, `gpio`, `uart`, `i2c`, …) | `dv_base`/`cip_lib` | Apache-2.0 | **Chosen.** Canonical industrial DV: TLUL bus + reggen RAL + predict-&-compare scoreboard + coverage + smoke/CSR/stress vseqs + coverage-closure CI (dvsim). |
| **Caliptra** (`soc_ifc`, sha512…) | Siemens **UVMF** (generated) | Apache-2.0 | Best *generator-vs-generator* lens; security IP, leans on commercial AXI VIP. |
| Accellera **ubus** | vanilla UVM | Apache-2.0 | Canonical but toy — no RAL, no coverage scoreboard. |
| `apb-uart-uvm-env`, OpenCores benches | vanilla UVM | mixed/none | Community/student; license + maturity gaps. |

`rv_timer` is the cleanest minimal cip_lib bench: exactly one bus agent, an external RAL,
a real SV reference-model scoreboard, a small covergroup set, and a textbook vseq library
— with no custom protocol agent or multi-stream muddle. (`gpio` is the richer variant: one
extra `pins_if` signal interface + a 9-covergroup model.)

## The core framing: *generate* vs *inherit*

Both QuickUVM and OpenTitan drive per-DUT boilerplate toward zero — by **opposite**
mechanisms:

- **OpenTitan** = a thin per-IP env that **inherits** fat base classes. `cip_base_env`
  auto-instantiates the TLUL agent, creates and locks the RAL, wires the reg adapter and
  sequencer, and connects the scoreboard's analysis taps; the CSR/TL/interrupt/alert test
  suites are inherited from `cip_lib`/`csr_utils`. The per-DUT code is small because the
  *framework* carries it.
- **QuickUVM** = a flat, **generated** per-DUT env with **no base-class dependency** — the
  code is explicit because the *generator* carries it.

Measured on `rv_timer` (line counts from source): **~1,492 hand-written per-IP lines**
ride on **~8,500+ inherited lines** (≈ 1 : 6), and of those 1,492 only the **scoreboard
(380, a genuine SV timing model)** and **~520 lines of stimulus vseqs** are truly
DUT-specific — the env/cfg/pkg/tb (~280) are boilerplate that just parameterizes base
classes. So a per-DUT env reduces to: **(1) a generated RAL, (2) ~280 lines of parameter
boilerplate, (3) one golden-model scoreboard, (4) a handful of stimulus sequences.**
QuickUVM *generates* (1-wiring), (2), the (3) predict/compare seam, and (4) — i.e. it
already replaces most of what `cip_lib` provides by inheritance.

## Component-by-component mapping

| `rv_timer` / `cip_lib` component | Role | QuickUVM equivalent | Gap |
|---|---|---|---|
| `tl_agent` (shared TLUL VIP, host+device) | register-bus agent | generated per-bench agent (initiator) | **No shared/reusable VIP; no reactive/responder (device) agent.** QuickUVM regenerates a fresh agent per bench |
| `tl_reg_adapter` | reg↔bus adapter | generated adapter **skeleton** (user fills) | Close (wiring matches); QuickUVM's is a skeleton, not a complete protocol adapter |
| ralgen reg block + `cip_base_env` auto lock/wire | external RAL + wiring | external reggen block + generated build/lock/`set_sequencer`/predictor (C4a/b/c) | **Close match** — both assume an external reg block; QuickUVM generates the wiring |
| `cip_base_scoreboard` (TL FIFOs, `do_read_check`, `process_tl_access` hook, TL-integrity/alert checks) | bus-access checking skeleton | predictor + comparator (Cummings) | Close philosophy; QuickUVM lacks the register-read-vs-RAL-mirror check structure + TL-integrity/alert checks |
| `rv_timer_scoreboard` (380-line SV timing model) | DUT golden model | predictor `predict()` body (SV **or** DPI-C, K0) | **Match** — both a user-written golden model |
| `rv_timer_env_cov` covergroups | functional coverage | generated config-driven covergroup (bins/illegal/transition/cross/goal, V1) | Close; no covergroup-arrays (wrapper pattern); **no auto register/field coverage** |
| **`csr_*_seq` library** (rw, bit_bash, aliasing, hw_reset, mem_walk) | automated RAL register tests, **inherited free** | basic `reg_test` (rw only) | **BIGGEST GAP** — the full CSR suite is RAL-generic and **generatable** |
| base_vseq helper lib + random/min/max/disabled/cfg vseqs | DUT stimulus | sequence library (random/incrementing/directed/nested) + vseqs (S2) | Match in kind; DUT-specific helpers stay user pragma |
| `common_vseq` → intr_test / alert_test / tl_errors / sec_cm_fi | protocol/security test dispatch | — | Gap — protocol/methodology-specific (largely **not** generatable) |
| env / env_cfg / test / tb (parameterize cip base) | bench boilerplate | generated env / env_cfg / base_test / tb_top / tb_pkg | **Match** — QuickUVM generates what OpenTitan inherits |
| reset coordination (`apply_reset`, reset-during-CSR), intr/alert vifs | methodology plumbing | `external_reset` (reset generator, X0) | Partial — no reset-during-CSR coordination, no interrupt/alert agents |
| dvsim regression + coverage merge + UNR + CI | closure infra | filelists + verible-lint CI | **BIG GAP** — roadmap **R1** |

## Prioritized gaps

**Generatable / roadmap-worthy:**
1. **🟢 RAL-driven CSR test suite (new — "C5")** — `csr_rw`, `csr_bit_bash`, `csr_aliasing`,
   `csr_hw_reset`, `mem_walk`. The single biggest gap *and* the most tractable: RAL-generic
   (UVM ships `uvm_reg`-based sequences), every register block needs it, and QuickUVM
   already wires the RAL — it is ~90% positioned. **Highest-leverage finding.**
2. **🟢 Register/field functional coverage from the RAL (V2)** — reggen emits reg
   covergroups; OpenTitan samples them. The comparison bumps V2's priority for
   register-heavy DUTs.
3. **🟢 Regression + coverage-closure infra (R1)** — seed management, coverage merge,
   test-list orchestration, a `make regress`. Confirmed essential by the dvsim flow.

**Bigger / architectural:**
4. **🟡 Reactive/responder (device) agent + a shared/reusable VIP notion** — QuickUVM's
   driver is initiator-only and each bench regenerates its own agent. Relates to **A2**.
5. **🟡 Reset coordination + interrupt/alert integration** — methodology plumbing beyond
   `external_reset`.

**Out of scope (correctly):**
6. **🔴 Protocol/security test machinery** (tl_errors, sec_cm fault injection, integrity)
   and a **mature hand-tuned VIP** (`tl_agent` with outstanding-req/integrity modeling) —
   protocol-specific, rightly left to a VIP, not a generic generator.

## Conclusion

The comparison **validates QuickUVM's architecture**: its generated
env/agent/scoreboard-seam/coverage/sequences/RAL-wiring is structurally what a real
OpenTitan block needs, and "generate flat" is a legitimate alternative to `cip_lib`'s
"inherit framework." The standout new opportunity is the **RAL-driven CSR test suite
(C5)** — the most-used, most-generatable capability QuickUVM is missing, directly
complementing the RAL wiring already shipped.

## Reference (verified from source, OpenTitan `master`, Apache-2.0)

- Per-IP: `hw/ip/rv_timer/dv/{tb/tb.sv, env/*, env/seq_lib/*, rv_timer_sim_cfg.hjson}`
- Framework: `hw/dv/sv/cip_lib/{cip_base_env, cip_base_scoreboard, cip_base_env_cfg,
  seq_lib/cip_base_vseq}.sv`, `hw/dv/sv/dv_lib/*`, `hw/dv/sv/tl_agent/*`
- CSR test library: `hw/dv/sv/csr_utils/{csr_seq_lib, csr_base_seq, csr_hw_reset_seq}.sv`
