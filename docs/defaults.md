# QuickUVM's sane defaults (and the evidence behind them)

> **Philosophy:** *simple by default, powerful when needed.* A generated bench should,
> out of the box, match what an experienced verification engineer would hand-write for a
> **medium-complexity, 2–4 agent subsystem** — and stay minimal for the single-agent case.
> This document records each default, the open-source consensus it rests on, and where the
> field has **no** consensus (so a choice is a deliberate house decision, not folklore).

## How these were derived

A survey of open-source UVM (SystemVerilog) verification environments and the two
methodology-backed generators most comparable to QuickUVM:

- **Doulos EasierUVM** code generator + coding guidelines (DVCon paper) and its Python
  clone **gen_uvm** — the closest analogues to QuickUVM.
- **Cliff Cummings / Sunburst** `uvmtb_template` (SNUG 2025) and the *UVM Scoreboards*
  (SNUG 2013) and *Virtual Sequencers/Sequences* (DVCon 2016) papers — the canonical
  methodology references.
- **Siemens UVM Framework (UVMF)** — vendor generator, Apache-2.0.
- **OpenTitan** `dv_lib`/`dv_base_lib` and **OpenHW** CV32E4*/CVA6 — production block/core
  benches.

Findings were cross-checked across ≥2 primary sources and adversarially verified; the
no-consensus flags below are where the survey explicitly **failed** to find a modal default.

## The defaults — dimension by dimension

| Dimension | Open-source modal default (evidence) | QuickUVM default | Status |
|---|---|---|---|
| **Agent structure** | one **active** agent per interface; sequencer+driver+monitor; `is_active` knob (default ACTIVE); single env [EasierUVM, Doulos, gen_uvm] | `active: true`; sqr+drv+mon; one env | **matches** |
| **Config objects** | one config object per component; **read-own-only** [EasierUVM] | `<dut>_env_cfg` + one `<agent>_cfg` each | **matches** |
| **Clocking** | one clocking block per interface; drive skew ≈ **20%** of the period; monitor samples outputs `input #1step`; DUT inputs sampled raw on the edge [Cummings `uvmtb_template`] | `cb1`/`mon_cb`; `drive_offset_pct: 20`; registered monitor = raw-in + `#1step`-out | **matches** |
| **Scoreboard** | **predictor + comparator** split; reference model isolated in **one** editable file; TLM analysis FIFOs + `compare()` [Cummings SNUG'13; OpenTitan; CV32E4*] | `<dut>_predictor` + `<dut>_comparator` + `<dut>_scoreboard`; model in `<dut>_reference_model.svh` (`predict()`) | **matches** (the canonical pattern) |
| **Virtual-seq mechanism** | `vseq_base` with `` `uvm_declare_p_sequencer ``; all vseqs extend it; subsequencer handles via `connect()`/`p_sequencer` **not** config_db [Cummings/Bergeron DVCon'16] | `<dut>_base_vseq` + `<dut>_virtual_sequencer`; `p_sequencer.<agent>_sqr` | **matches** (config_db path was *refuted*) |
| **Virtual-seq *policy*** | "add a vsqr **as a habit**"; the modal skeleton's Test "runs a virtual sequence to start one simple sequence per agent" [Cummings/Bergeron; EasierUVM] | **auto** vsqr + default vseq for ≥2 active agents (see below) | **matches** |
| **RAL** | opt-in, only when a register map is declared [uvmtb_template, gen_uvm, EasierUVM] | `register_model` opt-in | **matches** |
| **Whitebox observation** | black-box default; internal-signal access is opt-in/whitebox and separated out (bind files, backdoor) [OpenTitan, VA Cookbook] | black-box default; `probes:` opt-in (K2), observe-only | **matches** |
| **Sequence library** | **no consensus** on a fixed set — only "a base sequence + a vseq" is mandated | one `<agent>_seq`; richer library opt-in (S2) | **matches** (opt-in is the safe call) |
| **Layout** | modal = **layered** per-interface/env packages, `_agent/_if/_pkg/_env` [UVMF, EasierUVM] | **flat** single `<dut>_tb_pkg` | **deliberate divergence** — flat is simpler for the small/education case; layered is roadmap **F2** ("powerful when needed") |

## The one behavioral change: auto virtual-sequence layer

The strongest survey result QuickUVM closed: the modal multi-agent skeleton wires a
**virtual sequencer + a default virtual sequence** by default, and the canonical advice is
to add one *as a habit* (retrofitting later is painful). QuickUVM's vsqr/vseq layer (C2)
started opt-in; the default is now:

> **When there are ≥2 active agents and no explicit `virtual_sequences:`**, QuickUVM
> auto-scaffolds `<dut>_virtual_sequencer` + `<dut>_base_vseq` + a default `<dut>_vseq` whose body fires
> each active agent's base `<agent>_seq`; the default test runs it on `e.vsqr`.

- **Trigger** keys on **active** agents (a vsqr coordinates *driving* agents; passive
  monitor-only agents have no sequencer). A single driving agent ⇒ no vsqr.
- **Mode:** `parallel` (`fork…join`, concurrent stimulus on all interfaces) by default —
  realistic for a subsystem and deadlock-free since the per-agent base sequences are
  independent. Flip with one knob: `auto_vseq_mode: parallel | sequential` (default
  `parallel`).
- **Opt-out:** `auto_virtual_sequences: bool = true` — set false for the rare multi-agent
  bench that coordinates stimulus in test pragma code instead.
- **Launch precedence** (in the generated test): explicit `vseq:` → explicit `sequence:` →
  the auto vseq on `e.vsqr` → the primary agent's `<agent>_seq`.
- **Byte-identical** for every existing case: single-agent benches get no vsqr; benches
  with explicit `virtual_sequences:` are unchanged; only *new* multi-agent-without-vseqs
  configs gain the scaffold.

This is the philosophy in one feature: the vsqr (complexity) appears exactly when the
scenario (≥2 driving agents) needs it, and not before.

## Where the field has NO consensus — QuickUVM's stance

The survey explicitly could not find a modal default for these; QuickUVM's choices are
deliberate, and each stays **opt-in / simple-by-default**:

- **Reset modeling** — sources split between a dedicated reset *agent*, a reset
  *interface*, and a reset *sequence*. QuickUVM offers `external_reset` (reset interface +
  generator) **and** agent-port reset; pick per design.
- **Coverage policy** — "functional coverage on by default" was **refuted**; no modal
  per-agent-vs-central default exists. QuickUVM ships a light generic covergroup and a rich
  opt-in model (V1) — defensible precisely *because* the field hasn't converged.
- **Multi-stream / out-of-order scoreboard** — every documented scoreboard is **in-order,
  single-reference-model**. The 2–4 agent multi-stream case is an open problem in the field
  too; QuickUVM keeps the single-stream predictor+comparator baseline and roadmaps the
  cycle-aligned multi-stream scoreboard as **A2** (the C1 analysis fabric is the interim
  multi-agent path).
- **Messaging / objections / drain / verbosity** — no surviving evidence of a consensus.
  QuickUVM's sane picks: `UVM_MEDIUM` default verbosity, per-component message IDs,
  objection raise/drop around the top sequence/vseq, default drain 0 (knob optional).

## Sources

- EasierUVM coding guidelines + code generation — https://dvcon-proceedings.org/wp-content/uploads/easier-uvm-coding-guidelines-and-code-generation.pdf
- Doulos EasierUVM Code Generator reference — https://www.doulos.com/knowhow/systemverilog/uvm/easier-uvm/easier-uvm-code-generator/easier-uvm-code-generator-reference-guide/
- Cummings, `uvmtb_template` (SNUG 2025) — https://www.paradigm-works.com/hubfs/49408364/technical-library/Sunburst/CummingsSNUG2025SV_uvmtb_template_Testbenches_rev1_0.pdf
- Cummings, UVM Scoreboards (SNUG 2013) — https://www.scribd.com/document/253942642/CummingsSNUG2013SV-UVM-Scoreboards-pdf
- Cummings/Bergeron, UVM Virtual Sequencers/Sequences (DVCon 2016) — https://dvcon-proceedings.org/wp-content/uploads/using-uvm-virtual-sequencers-virtual-sequences.pdf
- OpenTitan dv_lib — https://opentitan.org/book/hw/dv/sv/dv_lib/index.html
- OpenHW CV32E4* env — https://docs.openhwgroup.org/projects/core-v-verif/en/latest/cv32_env.html
- Siemens UVMF — https://verificationacademy.com/topics/uvm-universal-verification-methodology/uvmf/uvm-framework/
- gen_uvm (Python EasierUVM clone) — https://github.com/asicnet/gen_uvm
