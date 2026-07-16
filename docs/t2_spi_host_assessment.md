# T2 — OpenTitan `spi_host` — assessment

> **This document was rewritten after an adversarial review found nine false statements in the
> first draft** — including a claim that a feature was "mutation-proved" when it had never been
> mutated. That is the *same* failure this project was publicly corrected for once already. The
> corrections are folded in below rather than quietly deleted, because they are more useful than
> the original claims were. Every simulation result cited has an executable recipe in
> [`examples/spi_host/MUTATIONS.md`](../examples/spi_host/MUTATIONS.md).

**The question T2 was built to answer:** the responder-timing features were designed against
`examples/spi_device` — whose SPI host **I wrote myself**, so I also chose its timing. A feature
that only works against RTL its own author designed has proved nothing.

---

## 1. What was actually proved, and how

| feature | proved against my own RTL? | proved here, on OpenTitan's? | how |
|---|---|---|---|
| `respond: prefetch` | yes (mutation) | **yes (mutation)** | **M3** — flip to `on_request`: 8/8 fail, `DEAD_RESPONDER` |
| per-lane `inouts` | **NO — never mutated, anywhere** | **yes — Standard (M4) AND Dual (M7)** | a scalar enable cannot express `0010` (std) or `0011` (dual): 8 × mismatch each |
| `clock[].source: dut` | no mutation | **elaboration + generation only** | `source: tb` ⇒ Xcelium `*E,MULDRN`; deleting the DUT connection ⇒ the generator refuses |

**`respond: prefetch` is load-bearing on real hardware.** M3 is the headline and it holds:
`on_request` never drives during a frame at all.

**Per-lane `inouts` had never been mutation-proved — anywhere.** `examples/spi_device` declares
**scalar** `miso`/`mosi`; it has no `inouts:` block and never did. The feature shipped on pytest,
byte-identity, and a clean elaboration. **T2 is the first bench to use it, and the first to falsify
it** (§4.1). The first draft of this document called it "mutation-proved against spi_device". That
was false.

**`clock[].source: dut` still has no *simulation* mutation.** Declaring it `source: tb` fails
elaboration, and deleting the DUT connection makes the generator refuse — both real, both
fail-closed, neither a runtime proof. By this repo's own bar (*a green bench that has not been
mutation-proved does not count*), that is a gap, and it is stated rather than papered over.

---

## 2. The fairness argument

TL-UL is replaced by a generic register bus, exactly as T1 did for hmac. For a generic block that
would be a fair objection — *you removed the hard part.* Here it is checkable:

    grep -rl tlul examples/spi_host/rtl/vendor/*.sv examples/spi_host/rtl/vendor/*.svh
    # -> no matches

*(The first draft printed this without the `*.sv`/`*.svh` restriction — where it matches the vendor
README's own prose and returns rc=0. The one command inviting a hostile reader to check did not
produce the output it claimed. Fixed here and in the vendor README.)*

**`spi_host` is an SPI controller. The bus under test is SPI, not TL-UL** — TL-UL is only how
firmware configures it. The FSM (CPOL/CPHA/FULLCYC/CLKDIV/CSAAT), the shift register, the byte
packers, the TX/RX/CMD FIFOs, the per-lane `sd_en_o` and the gated `sck` are all below the cut and
vendored byte-for-byte. TL-UL lives in three files; all three are replaced.

**Limit:** the vendor README pins *branch `master`*, not a commit SHA. The snapshot cannot be
reproduced exactly, and it is post-tapeout master rather than a silicon revision. "Real, taped-out
RTL" is true of the *design*; it is not a claim about this exact source snapshot.

---

## 3. Measurement

Two corrections from the review, both of which cut against the tool:

1. The first draft's "generated" column was the **whole tree**, hand-written lines included. That
   inflates the denominator and flatters the percentage.
2. Lines inside a pragma region are **not necessarily hand-written**. Regenerating into an empty
   directory reveals which pragma content is untouched **generator default** text. Here that is 28
   lines — including 15 lines of `dut_logic` in `gen/spi_host_ot.sv`, **a DUT stub the bench does
   not even compile** (`sim/xrun.f` builds `rtl/spi_host_ot.sv` instead).

Corrected, same script over every target:

| target | tree | generated | in-pragma | of which default | **really hand-written** | % of tree |
|---|---:|---:|---:|---:|---:|---:|
| `hmac` (T1) | 1,431 | 1,257 | 174 | 42 | **132** | 9.2% |
| **`spi_host` (T2)** | 2,001 | 1,780 | 221 | 28 | **193** | 9.6% |
| `rvtimer` | 1,939 | 1,837 | 102 | 39 | **63** | 3.2% |

**The first draft claimed "the hand-written code did not grow with the difficulty of the block."
That is false.** It grew: **132 → 193, about +46%**, for a block that is full-duplex, serial,
tri-state, on a clock the TB does not own, with two agents and a mode-aware protocol.

What survives is weaker, and worth stating precisely: **the hand-written *fraction* stayed at
roughly a tenth of the tree** (9.2% → 9.6%) while the block got substantially harder — and every one
of the 193 lines is protocol or model code: the SPI shift loop in both directions, the register-beat
timing, the CSR programming recipe, the golden model, the liveness checks. **No generator emits
protocol logic**; OpenTitan's own `uvmdvgen` ships an empty `get_and_drive()` (per
[`docs/reproduce_campaign.md`](reproduce_campaign.md), not independently verified here).

**RTL:** 3,537 lines vendored unmodified (28 files); ~300 lines ours (the register block, and the
top + pad ring).

---

## 4. What the foreign RTL exposed

### 4.1 A feature that had never been falsified — and the bench hole that hid it

The review found per-lane `_oe` had no mutation behind it. **The first attempt to supply one
failed:** driving all four lanes — what a scalar enable forces — left the bench **green**.

The reason was a real defect: **the bench checked only what the *host* received (RXDATA), and never
what the *device* received.** Half of a full-duplex transfer was unverified — and lane-0 contention
lives in exactly that half. With the device's MOSI check added, the same mutation now yields **8 ×
`MOSI_MISMATCH` — "the device received 00, the host sent 5a"**.

A false claim → a failed proof → a genuine bench defect → the feature finally proved. **The failed
mutation was worth more than the passing bench.**

Dual/Quad (`SPI_SPEED=1/2`, RdOnly reads) then exercise the feature in **two more lane patterns**,
and this is where per-lane ownership is decisively load-bearing. The DUT drives, and the device
must own, exactly:

| mode | device enable | a scalar enable can make it? |
|---|---|---|
| Standard (M4) | `0010` | **no** |
| Dual (M7) | `0011` | **no** |
| Quad (M8) | `1111` | yes |

**A scalar enable (only `0000` or `1111`) can produce Quad, but *neither* Standard nor Dual.** M7
mutates the dual device to the standard subset `0010`; `sd[0]` floats and the read fails 8/8. So
per-lane `_oe` is not a nicety — two of the three required patterns are inexpressible without it.
Quad's `1111` is scalar-achievable, so quad alone does not *require* per-lane; M8 (drive `0011`
instead) still fails, which proves the RX check discriminates lane count but not that per-lane is
necessary for quad. That distinction is stated because the earlier draft would have blurred it.

### 4.2 The phantom-clock guard fired on correct input

The guard (PR #57) matched `.clk(...)`, assuming the DUT's **port** is named after the TB's clock
**net**. OpenTitan's is `clk_i`. It therefore **refused to generate a perfectly correct bench**, and
would have for nearly every industrial DUT (`clk_i`, `i_clk`, `aclk`). A guard that fires on correct
input is worse than none: it teaches users to reach for `--allow-drop`. Fixed to match the net as an
*actual*. **Invisible against RTL I named myself.**

### 4.3 Two traps — and one of them is mine, not OpenTitan's

* **`COMMAND` is `hwext`+`hwqe`: no storage.** The command launches on the **write strobe**. This is
  OpenTitan's, attested by the vendored `spi_host_reg_pkg.sv` (`qe` on every COMMAND sub-field).
  Drive it from a value and the DUT sits idle forever, silently.
* **`CONTROL.OUTPUT_EN` gates every output and resets to 0.** The *field* is OpenTitan's (vendored
  reg_pkg). **The gating logic and the reset value live in `rtl/spi_host_ot.sv` and
  `rtl/spi_host_reg_generic.sv` — files I wrote.** The vendored core has no `output_en` port at all.
  The first draft called this a trap that "ships inside OpenTitan's own reset state". It does not:
  **I wrote the trap, then tripped over it.** It reproduces upstream behaviour faithfully, but
  upstream's `spi_host.sv` is not in this tree and cannot be cited from it.

The *shape* is still worth knowing: with `OUTPUT_EN` clear the DUT drives nothing, and the pull-ups
float the bus to `0xff` — **quiet, legal, no X, no error.** A check asking only "is there an X on the
bus?" passes while testing nothing.

Dropping it fires **`DEAD_RESPONDER`** — and *only* because PR #59 changed that counter from "items
fetched" to "transfers driven". With `csb` never falling, the device driver parks forever inside
`drive_transfer`: it fetched an item and drove nothing. **That fix was made on a prediction from
this target's build spec, before the bench existed, and it was right.**

### 4.4 A clocking-block drive can delete its own pulse

**A clocking-block drive issued the instant `@vif.cb1` returns lands on the same clocking event as
the drive before it.** The driver's `req <= 1'b0` deassert therefore **overwrote its own
`req <= tr.req`**.

Precisely: **11 of 26 driven beats reached the wire, not 0.** Back-to-back beats *merge* (the next
assert overwrites the previous deassert); delay-separated beats *vanish* (the deassert overwrites
its own assert). The first draft said "every register beat vanishes" — refuted by its own probe.

The bench's first run reported **`TEST PASSED — 2622 Ran / 2622 Passed`**, with one `UVM_ERROR:
NO_RXDATA`. Those 2,622 "passes" were **idle bus beats echoing themselves**. Without the end-of-test
liveness check it was a clean green bench measuring nothing.

**How it was found is the reusable part.** Several rounds of theorising about monitor sampling skew
produced nothing. One line in `tb_top` settled it:

    always @(posedge clk) if (regbus_if_inst.req) n++;   // -> 11 edges, for 26 driven items

**When a signal is missing, probe the wire before reasoning about the skew.**

---

## 5. What OpenTitan corroborated

`spi_host_core`'s port is `output logic [3:0] sd_en_o` — **a per-lane output enable.** A scalar
enable cannot *express* per-lane ownership: it cannot say "drive lane 1, release lane 0". (It would
still *connect*, with a width warning — the first draft said "cannot connect at all", which is not
true of SystemVerilog.)

**This is corroboration, not independent confirmation.** The gap was found *by reading OpenTitan's
device-mode DV agent* during T2 scoping — the fix was written *for* this target, not predicted blind
and later vindicated by silicon. The first draft implied the latter.

---

## 6. Reasoning vs. running — the honest tally

The first draft claimed *"none of the three was predicted by anyone; all three were found within
minutes of executing."* **Both halves are false**, and it contradicted this document's own §4.3.

The real record:

* **Reasoning got things right.** PR #59's `DEAD_RESPONDER` fix came from the build spec's
  prediction, before the bench existed, and the real scenario later fired exactly as predicted. The
  monitor-prologue removal likewise pre-empted a problem that never materialised.
* **Reasoning also produced false alarms:** "K0 breaks" (T1, twice); "CPOL=1 will misalign the
  monitor prologue" (it does not).
* **And several things could only be found by running:** the `cb1` drive collapse, the failed M4 and
  the bench hole behind it, the clock-guard false positive.

The defensible claim is narrow: **when a signal is missing, or a bench is unexpectedly green, probe
before theorising.** Not "reasoning is useless" — the tally does not support that, and the first
draft rigged it by re-labelling reasoning's hits as "design" and counting only its misses.

---

## 7. Honest limits

* **This is not OpenTitan's DV environment.** It reproduces the *shape* their bench needs — a
  device-mode SPI agent on a DUT-driven clock, tri-state lanes, a register-programming sequence —
  not `cip_lib` inheritance, their testplan, or TL-UL protocol coverage.
* **`clock[].source: dut`** — now has a runtime mutation too (`MUTATIONS.md` M9): a dead
  observed clock (`sck` forced constant) yields `DEAD_RESPONDER` and the test **terminates**
  (wall-clock bound), proving it goes RED not hang. Was gen/elab-only.
* **The vendor snapshot is unpinned** — branch, not SHA (§2).
* **Dual/Quad are RdOnly single-byte reads, mode 0 only** (`SPI_SPEED=1/2`). Enough to prove per-lane
  ownership in the `0011`/`1111` patterns; not a full dual/quad protocol (no WrOnly-dual, no CPHA=1
  in these modes, no multi-byte).
* **RAL — tried, and it needs a custom frontdoor** (was "untried"). Wiring `register_model:` over
  the generic register bus **structurally integrates [C]**: a hand-written `uvm_reg_block`, the
  generated adapter (`reg2bus`/`bus2reg`), the `uvm_reg_predictor`, and the C5 `hw_reset`/`bit_bash`
  tests all generate, connect, and *run*. But the register bus returns **read data registered** (one
  clock late), and the generic monitor+adapter path delivers **stale read values** — `CONTROL` reads
  `0x0`, not its `0x7f` reset — with `Response queue overflow` on the driver's read-response path.
  **This is the pipelined-read wall, and it needs a custom `uvm_reg_frontdoor`** (QuickUVM has the
  `register_model.frontdoor:` knob for exactly this) — the same conclusion the real `spi/quickuvm_tb`
  RAL integration reached. Not built to green here; the finding is that RAL *integrates* but this bus
  *shape* requires the frontdoor escape hatch, not that RAL is absent.
  * **RESOLVED — and the conclusion was too specific** (`examples/ahb_regs`, built on a registered-read
    AHB-Lite bus). Running it shows the real requirement is **two-phase bus TIMING**, not a
    `uvm_reg_frontdoor` per se: a naive single-cycle capture reproduces the exact stale-read
    (every register reads the *previous* one's value, 4 UVM_ERRORs), and a **two-phase DRIVER seam**
    (drive the address phase, `HTRANS=IDLE`, advance to the data phase, capture the now-valid `HRDATA`)
    closes it with the **generic adapter** — all three CSR tests green, mutation-proved. So a custom
    frontdoor is *not* needed for an in-order pipelined bus; the `register_model.frontdoor:` knob is for
    genuinely *decoupled* request/response channels (TL-UL's a/d), which AHB is not. (spi_host's extra
    `Response queue overflow` was its serial full-duplex responder, a separate axis.)
  * **The `csr_excl` wall is real and identified [C]:** `COMMAND` (a write launches a transfer),
    `RXDATA` (destructive read), `TXDATA` (write-only) and `STATUS` (hw-driven) each need
    `NO_REG_BIT_BASH_TEST`; `CONTROL.SW_RST` resets the core mid-walk. `CSID` is the *safe* one — a
    plain scratch flop (`command_csid_i` hardwired to 0, `NumCS = 1`) — correcting the first draft's
    false "CSID bricks the DUT" claim. (Their bit_bash validation is blocked behind the read-path
    wall above.)
  * **A cross-agent nuance [C]:** on this two-agent bench a CSR-only test trips the SPI device's
    `DEAD_RESPONDER` liveness — the generated CSR test disables the data-path *scoreboard*
    (`sb_enable=0`) but not the responder's liveness. Gating that liveness on the same `sb_enable`
    (a small generator change, mutation-verified not to weaken the real check) resolves it; a
    candidate improvement, not built into main.
* **Only 1-byte segments.** LEN > 1 and CSAAT chaining are unexercised. (A `clkdiv` sweep
  IS exercised now — `+SPI_CLKDIV`, MUTATIONS.md M10: divisors 2–32 all pass, proving the
  edge-relative device timing is divider-independent.)
* **No simulation logs are committed.** Results are reproducible from `MUTATIONS.md`, not archived.
