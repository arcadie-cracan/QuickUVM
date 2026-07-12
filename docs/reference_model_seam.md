# The reference-model seam (K0) — how to plug in a golden model

QuickUVM does not *write* your golden model. It generates the **seam** so one drops in. This
page is about choosing the right door, because there are two and the obvious one is usually
the wrong one.

> **TL;DR** — `reference_model.language: c` generates a bridge for a **pure scalar function**.
> A real golden model is a **library**, and it uses a different door: keep `language: sv`,
> import the library yourself, and call it from the `prediction_logic` pragma. The predictor
> is a *class*, so it can hold state. `examples/hmac/` is the worked example.

## The seam

The scoreboard routes each monitored transaction through a predictor:

    <dut>_predictor extends uvm_subscriber       <- a COMPONENT (it can hold state)
      `- predict(item) -> expected_item          <- body in <dut>_reference_model.svh
           `- pragma quickuvm custom prediction_logic   <- your code
      `- pragma quickuvm custom class_item_additional   <- your state

Two properties of that shape do more work than they look like:

1. **`predict()` is a method on a class**, so the predictor can carry state between calls —
   accumulate a stream, remember a key, stash a result.
2. **Everything the model needs is usually already a transaction.** A register write, a FIFO
   push, a control-register trigger, a read of the result — on a bus, all of these are items
   on the same monitored interface.

Together they mean the seam needs **no stream or event vocabulary**, as long as every event
the model depends on is *observable as a transaction*. That is true far more often than it
looks — see the T1 write-up ([`t1_hmac_assessment.md`](t1_hmac_assessment.md)), where the
prediction that this seam would break turned out to be **wrong**.

It is not *always* true. An ISS you must **step** on instruction retirement (Spike, in a CPU
bench) is genuinely a different contract, because the model advances on an event the TB does
not drive.

## Door 1 — `language: c`: a pure scalar function

Setting `reference_model.language: c` generates:

* an SV marshaling bridge (`import "DPI-C" function void <dut>_predict(...)`), and
* a `<dut>_reference_model.c` stub — the only file you edit.

The signature is derived from the primary agent's fields: **scalars in, scalar pointers out,
`<=64` bits each, one call per transaction.**

That is a genuine convenience for a small, pure, combinational model.
[`examples/sat_adder/`](../examples/sat_adder/) is exactly that case: a saturating adder whose
golden model is a handful of lines of C.

**It is a convenience, not the general mechanism.** If your model does not have that shape,
you are not blocked — you are using the wrong door.

## Door 2 — a real golden-model LIBRARY

Real golden models are not pure scalar functions. They are libraries:

| golden model | its actual signature |
|---|---|
| OpenTitan `cryptoc` | `svOpenArrayHandle` byte streams in, an **8-word array** out |
| Spike (ISS) | a `chandle` you **step**, errors pulled from a queue |
| Caliptra's predictor | **shells out to Python** and `$fscanf`s a file back |

None fits the bridge. **None needs it.** Do this instead:

1. Keep `reference_model.language: sv`.
2. Declare the library's own DPI import — add its package to `project.imports`, or drop the
   `import "DPI-C" ..."` into the tb_pkg `imports` pragma region.
3. Add the C sources to the filelist (the `extra_run_args` pragma in `run.f`, or your own
   `sim/` filelist).
4. Hold whatever state you need in the predictor's `class_item_additional` pragma.
5. Call the library from the `prediction_logic` pragma.

### The worked example: `examples/hmac/`

[`examples/hmac/`](../examples/hmac/) is OpenTitan's HMAC block, checked against OpenTitan's
own vendored `cryptoc` C library. Its golden model is stateful and streaming — message words
accumulate, a `CMD.hash_process` write *triggers* the hash, and the digest appears many cycles
later across a register array — and the whole thing lives inside pragma regions:

* one line of YAML: `imports: [cryptoc_dpi_pkg]`
* the accumulated message + key + digest in `class_item_additional`
* `c_dpi_HMAC_SHA256(key, 32, msg, len, digest)` called from `prediction_logic`

Regenerating that bench is a **no-op** (`0 updated, 26 unchanged`) — every hand-written line
is pragma-contained. **1,262 lines generated, 174 hand-written (12.1%).**

That model is inexpressible in the `language: c` bridge on three counts (an unbounded byte
stream, a 1024-bit key, a 256-bit array result) — and it did not need it.

## Choosing

| your golden model | door |
|---|---|
| a small pure function, scalars, ≤64-bit, one call per transaction | `language: c` |
| a C/C++ **library** (arrays, streams, buffers, a handle) | `language: sv` + your own DPI import |
| already SystemVerilog | `language: sv` (the default) |
| an ISS you **step** on an event the TB does not drive | `language: sv` + your own DPI; see the T5 note below |

**Deferred:** extending the generated bridge to array/stream marshaling
(`svOpenArrayHandle`, packed `>64`-bit). It is a real follow-up, but it is **not urgent** —
the escape hatch works today, and for a library it is arguably the more honest interface,
because the library's signature is the library's, not something a generator should be guessing.

**Known limit (T5, Ibex):** a model that must be **stepped** — a `chandle` advanced when the
DUT retires an instruction — is a contract the seam has never been tested against. That is a
live prediction, not a settled question.
