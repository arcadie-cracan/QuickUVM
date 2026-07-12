# odbus — bidirectional (`inouts`) ports

An **open-drain, wired-AND bus** — the shape of I2C's SDA/SCL. The DUT and the testbench
share one wire. Neither can drive it high: each may only pull it **low** or **release** it,
and a pullup makes it read 1 when everyone has let go. That is why two devices can pull low
at the same instant with no contention.

## Why `inouts` is a third category

Neither `inputs` (TB-driven) nor `outputs` (DUT-driven) can express a net that must be
**released**. So the port map has three keys, completing the SV direction keywords:

| YAML | SystemVerilog |
|---|---|
| `inputs` | `input` |
| `outputs` | `output` |
| `inouts` | `inout` |

```yaml
ports:
  outputs:
    - {name: dut_low, width: 1}
  inouts:
    - {name: sda, width: 1, open_drain: true, pullup: true}
```

Each inout port yields **three** transaction fields:

| field | meaning |
|---|---|
| `<n>_o` | what we drive (`rand`) |
| `<n>_oe` | whether we drive at all (`rand`) — **releasing is a first-class choice** |
| `<n>` | the **resolved** line (sampled; never what we drove) |

`open_drain: true` means driving a 1 **is** releasing — the line can never be driven high.
`pullup` is **mandatory** with it, and that is not a style preference: with no pullup an
open-drain line floats to **X** the moment everyone releases, and every downstream sample is
silently poisoned.

## Run

```bash
cd sim && xrun -f xrun.f +UVM_TESTNAME=rand_test   # -> TEST PASSED, 62/62
make -C gen regress                               # 3 seeds, coverage merged
```

The scoreboard checks the **wired-AND contract itself**: the shared line is low iff
*somebody* pulls it low, and reads 1 (never X) when everyone releases. The interesting
coverage cross is `sda_oe x dut_low` — **both** pulling low at once, which is legal and must
not produce X.

## The check is real, and it took work to make it so

The first version predicted the resolved line and then **never compared it** — so a DUT that
broke open-drain entirely (driving high, causing contention) still reported **62/62**. Four
separate bugs were hiding behind that green bar, and each one only surfaced once the compare
was made to work:

| bug | symptom |
|---|---|
| `do_compare` skipped the inout line | nothing was checked at all |
| the DUT was never connected in `tb_top` | TB and DUT sat on **different wires** |
| the line was sampled with the *inputs* | resolved line compared against the DUT's drive state from the **next cycle** |
| `do_copy` dropped `_o`/`_oe` | the predictor modelled a bus **nobody was driving** |

Mutation-proved, both ways a tri-state contract can break:

| mutation | result |
|---|---|
| DUT drives **high** instead of releasing (contention → X) | **FAIL** 10/62 |
| **pullup removed** (released line floats → X) | **FAIL** 37/62 |
