# HMAC — campaign target T1

OpenTitan's HMAC block, reproduced to answer one question: **does K0's reference-model seam
survive a real, stateful, library-backed golden model?**

**Verdict: yes — K0 is EXTENDED, not bypassed.** See
[`docs/t1_hmac_assessment.md`](../../docs/t1_hmac_assessment.md).

The entire streaming golden model — accumulate message words, trigger on a CSR write, call
OpenTitan's vendored `cryptoc` C library over DPI, serve the digest back across a register
array — lives **inside pragma regions**. Regenerating is a no-op (`0 updated, 26 unchanged`).

| | |
|---|---|
| Generated | 1,262 lines |
| Hand-written (all pragma-contained) | 174 lines — **12.1%** |
| Result | 6/6 on Xcelium (2 tests x 3 seeds), coverage merged |

## What is vendor, what is ours

* **Vendor, unmodified** (lowRISC/opentitan, Apache-2.0): `hmac_core`, `prim_sha2_32`,
  `prim_sha2`, `prim_sha2_pad`, `prim_fifo_sync`, `prim_packer` — every line of the CRYPTO —
  and the `cryptoc` C golden model under `dpi/`.
* **Ours** (the declared bus normalisation): `hmac_reg_generic.sv` replaces the TL-UL CSRs,
  and an address-decoded window replaces the TL-UL message-FIFO adapter.

## Run

```bash
make -C gen regress          # 2 tests x 3 seeds -> 6/6, coverage merged
cd sim && xrun -f xrun.f +UVM_TESTNAME=hmac_test   # the RFC 4231 vector
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test   # random register traffic
```

`hmac_test` drives RFC 4231 Test Case 1 (key = 0x0b x20, msg = "Hi There") and the
**generated scoreboard** checks the digest against the C model. Reversing the DUT's key word
order makes it fail 3/6 — the check is real.

`sim/tb_smoke.sv` is a directed RTL test that validates the DUT wrapper itself against RFC
4231, so a wrapper bug can never be misread as a QuickUVM failure. It earned its keep: it
caught a 5-bit `wmask_ones` overflow that made the engine hash a zero-length message.
