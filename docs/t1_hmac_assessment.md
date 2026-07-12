# T1 — OpenTitan HMAC: does the K0 reference-model seam survive a real golden model?

Campaign target T1 ([`reproduce_campaign.md`](reproduce_campaign.md)). Bench:
[`examples/hmac/`](../examples/hmac/). Companion to
[`maturity_assessment_rv_timer.md`](maturity_assessment_rv_timer.md).

## The verdict, up front

**K0 is EXTENDED, not bypassed.** The generated scoreboard **survives**: the entire
streaming HMAC golden model — accumulate, trigger, DPI call into a C crypto library, and a
digest served back across a register array — lives **inside pragma regions**. Nothing
outside them was touched.

**Proof (not assertion):** after the bench was written and passing, re-running
`quick-uvm generate` reports **`0 created, 0 updated, 26 unchanged`** and produces an
**empty diff**. Every hand-written line is pragma-contained by construction.

| | |
|---|---|
| Generated (bucket D) | **1,262** lines |
| Hand-written, all inside pragma regions (bucket A) | **174** lines — **12.1%** |
| Result | `hmac_test` + `rand_test`, **6/6 on Xcelium** (3 seeds each), coverage merged |
| Mutation proof | reversing the DUT's key word order → **3/6 FAIL**, nonzero exit |

For scale: Caliptra's UVMF-generated SHA512 bench is **17.4%** human — the *same*
mechanically-counted metric (both tools delimit user code with pragma regions). QuickUVM's
12.1% on a comparable crypto block is a favourable, like-for-like data point. It is
indicative, not exact: Caliptra's bench also carries an HDL-side BFM and emulation
partitioning that we deliberately do not generate.

## The prediction was WRONG — and the campaign rule says say so

The campaign's selection rule is that every target's failure is **predicted before the
build**, and any prediction that misses is **reported as a miss**. This one missed.

**Predicted:** *"K0 breaks. There is no vocabulary in the predictor seam for accumulate →
trigger-on-control-event → compare-later-across-N-registers."* Stated even more strongly
mid-build: *"there is no single transaction whose `predict()` could return the digest."*

**That was wrong**, for a reason that is obvious in hindsight and worth writing down:

1. `predict()` is a **method on a class** (`<dut>_predictor extends uvm_subscriber`), and
   that class has a `class_item_additional` pragma region. So the predictor can be
   **stateful**.
2. **Every HMAC event *is* a transaction on the same register bus.** The message words are
   MSG_FIFO *writes*. The trigger is a `CMD.hash_process` *write*. The digest is delivered
   by `DIGEST_i` **reads**. There is no event outside the transaction stream.

So a stateful predictor reconstructs the "stream" trivially: accumulate on FIFO writes,
compute on the CMD write, serve the stashed words on the DIGEST reads. The seam was never
the problem.

**The general lesson, which generalises past HMAC:** a predictor seam does not need
stream/event vocabulary *as long as every event the model depends on is observable as a
transaction on a monitored interface*. That is true far more often than it looks. It will
**not** be true for T5 (Ibex), where the model must be *stepped* against an ISS on
instruction retirement and holds a `chandle` — a genuinely different contract. Keep the
prediction for T5; retire it for HMAC.

## The real finding, which is narrow and cheap

**K0's generated DPI-C bridge (`reference_model.language: c`) models a golden model as a
pure scalar function.** It emits one `<dut>_predict(char a, char b, char *out)` and
**hard-rejects any field wider than 64 bits** (`models.py`, the ≤64-bit scalar-marshaling
rule).

Real golden models are not pure scalar functions. They are **libraries**:

| golden model | actual signature |
|---|---|
| OpenTitan `cryptoc` (this bench) | `svOpenArrayHandle` byte streams in, an **8-word array** out |
| Spike (T5, Ibex) | a `chandle` you **step**, with errors pulled from a queue |
| Caliptra SHA512 (T4) | their predictor **shells out to Python** and `$fscanf`s a file |

None of the three fits the bridge. **But none of them needs it**, because the seam already
has the escape hatch: declare `import "DPI-C"` yourself in the package's `imports` pragma
region and stay on `language: sv`. That is exactly what this bench does — 1 line of YAML
(`imports: [cryptoc_dpi_pkg]`) plus a DPI call inside `prediction_logic`.

So the gap is **positioning, not architecture**:

- **Do:** document that `language: c` is for *simple scalar per-transaction models*, and
  that a real C **library** is wired by importing it yourself (`language: sv` + the
  `imports` pragma). Today the docs imply `language: c` is the way to bring a C golden
  model, which is misleading for the realistic case.
- **Optionally:** extend the bridge to array/stream marshaling (`svOpenArrayHandle`, packed
  >64-bit). Already flagged in-code as a follow-up. **Not urgent** — the escape hatch works
  and is arguably the more honest interface for a library.
- **Do not:** redesign K0. The seam is sound.

## Method & fairness

Per the campaign's declared normalisations ([`reproduce_campaign.md`](reproduce_campaign.md) §5):

- **Bus normalisation.** TL-UL → a generic single-cycle register bus. `hmac_core.sv` was
  *verified* to contain **zero** TL-UL references, so this is a wrapper, not a rewrite. Two
  bus touchpoints were replaced: `hmac_reg_top` (CSRs) and `tlul_adapter_sram` (the
  message-FIFO window). **Every line of the CRYPTO is vendor and unmodified** — `hmac_core`,
  `prim_sha2_32`, `prim_sha2`, `prim_sha2_pad`, plus `prim_fifo_sync` and `prim_packer`.
- **`prim_packer` was deliberately KEPT** even though our bus is word-aligned: its
  `flush_done` gates `hmac_core`'s `hash_process`, so it is load-bearing sequencing, not
  byte-packing plumbing.
- **Scope: SHA-256 / HMAC-SHA-256 only.** SHA-384/512 and the key-length matrix add
  combinatorics and no architectural insight.
- **Checking scope, stated explicitly** (rv_timer's 42-line bucket-A *understated* fidelity
  because its checking scope was smaller, and we said we would not repeat that silently):
  this bench checks the **digest**, the **CFG/KEY readback**, and random register traffic.
  It does **not** check STATUS/fifo_depth, error codes, or interrupts.
- **The DUT wrapper is an INPUT, not a QuickUVM deliverable** (5,017 lines vendor RTL + 473
  lines of our bus wrapper), and is excluded from the buckets.

**The DUT was validated before the bench existed**, by a directed RTL smoke test against RFC
4231 TC1 — precisely so that a wrapper bug could never later be misread as a QuickUVM
failure. It earned its keep immediately: `wmask_ones` was 5 bits wide and shifted `>>3`; a
full 32-bit mask sums to 32, overflowing 5 bits to **zero**, so `message_length` never
incremented and the engine hashed a *zero-length* message. `message_length` is in **bits**.

## Incidental findings

- **The fail-closed merger caught a marker bug I introduced**, refusing to regenerate and
  destroy hand-written code (`'end' for section 'body' has no matching 'begin'`). The
  preservation system worked exactly as designed, on a real mistake, unprompted.
- **Reading `DIGEST` too early returns the SHA-256 initial constants** (`6a09e667`,
  `bb67ae85`, …) — a very recognisable "you read it mid-flight" signature. HMAC runs an
  inner *and* an outer hash, so it needs hundreds of cycles, not tens.

## Still open on T1

- **RAL + the C5 CSR suite over the register ARRAYS** (`KEY_0..7`, `DIGEST_0..7`) — T1's
  *secondary* axis, and genuinely untested by rv_timer's five scalar registers. Needs a
  hand-written `uvm_reg_block` with a register array (the `regfile`/`rvtimer` pattern).
- **File-driven stimulus** — OpenTitan's bench reads NIST vector files to build sequences;
  QuickUVM has no vector-file sequence kind. Small, real, not yet a roadmap item.
