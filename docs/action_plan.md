# QuickUVM Action Plan

Status: in progress. Track A (pragma-preservation hardening) is the priority and is
fully scoped for execution. Track B (functional gaps) is roadmapped.

## Progress log
- **A0/A1/A2 — DONE.** Hardened `merger.py` (structured parse, `validate_markers`,
  fail-closed `merge()` → `MergeResult`, default-vs-user distinction), backup safety
  net in `generator.py`, CLI `--allow-drop`/`--no-backup` + friendly `MergeError`.
  New tests in `tests/test_merger_dataloss.py`; full suite green (54 tests).
- **Latent defect found & fixed (part of A3.1):** Jinja `{%-` trimming was eating the
  newline around pragma markers in **7 templates**, gluing generated code onto the
  marker lines. Consequence: the *old* merger's `begin\n` regex silently failed to
  preserve those hooks — preservation was largely non-functional. Markers are now
  isolated on their own lines; validated clean across the example TB.
- **A3.3 — DONE (and escalated to a correctness fix).** The aggressive `{%-` trimming
  did not just produce run-on lines; in the monitor it glued sampling assignments onto
  `//` comment lines, **silently commenting out the DUT sampling** (broken TB). Root
  cause: `{%-` left-strips eating preceding newlines while `trim_blocks` already handles
  trailing ones. Fixed by removing the redundant `-` left-strips globally (123 sites);
  comment-swallows-code is now structurally impossible. Also fixed a real filelist bug
  (`pkg.f` glued `tb_pkg.svreg_if.sv`). Locked in by
  `test_monitor_sampling_code_is_active_not_commented` and idempotency tests.
- **A4 — DONE.** `status` now classifies user-modified / orphaned / out-of-band /
  malformed-markers per file (no more default-stub false positives).
- **A5 — DONE.** `pkg.f`/`run.f` carry `extra_pkg_files` / `extra_run_args` fences.
- **A6 — DONE.** `docs/code_preservation.md`, `docs/comparison.md`, README updated.
- **Suite: 68 tests green.** Remaining: minor cosmetic blank-line tidy in a few
  templates (non-blocking); Track B (RAL etc.).

This plan was produced from a comparison of QuickUVM against:
- **Siemens UVM Framework (UVMF)** `2026.1` — `regen.py` pragma merge engine (the model we mirror)
- **Doulos Easier UVM** code generator — separate-include-file preservation school
- **icdk `uvmgen`** (Dragon-Git) — unconditional overwrite, no preservation
- **`gen_uvm`** (asicnet) — EasierUVM rewrite, preservation mechanism not retained

**Headline finding:** QuickUVM already has a pragma merger
([`quick_uvm/merger.py`](../quick_uvm/merger.py)) but it can *silently lose user code*,
so it is not yet trustworthy. Track A closes that gap to UVMF parity.

---

## Design principle (adopted from UVMF): fail-closed

The merger must refuse to write when it cannot account for every saved user section,
unless the user explicitly opts out (`--allow-drop`). A backup always exists as a
safety net.

---

# Track A — Harden pragma preservation to UVMF parity

### Phase A0 — Characterization tests (pin current behavior)
- A0.1 `tests/test_merger_dataloss.py` documenting today's gaps (orphaned section,
  missing `end` marker, duplicate same-name sections, default stub treated as user code).
- A0.2 Golden snapshot of the `simple_reg` generated file set for regression diffing.
- Acceptance: data-loss tests start as `xfail`, flip to pass after A1/A2/A3.

### Phase A1 — Merger core hardening (`quick_uvm/merger.py`)
- A1.1 Structured `Section` dataclass `{name, body, begin_line, end_line}` +
  line-by-line `find_sections()`.
- A1.2 `validate_markers()` — unbalanced/mismatched/nested/duplicate → error before any write.
- A1.3 Fail-closed `merge()` returning `MergeResult{text, preserved, created, orphaned}`;
  raise `MergeError` on orphans unless `allow_drop=True`.
- A1.4 Empty-vs-user distinction: compare existing body to freshly rendered default
  instead of "non-whitespace = user code".
- Acceptance: A0.1 tests pass; orphan/unbalanced raise; duplicates deterministic.

### Phase A2 — Backup safety net (`quick_uvm/generator.py`)
- A2.1 Copy existing file to backup before overwrite (gated by `backup=True`).
- A2.2 Thread `allow_drop` and `backup` from `generate_all` → `_write` → `merge`.
- Acceptance: a would-drop regen is recoverable from backup; `--no-backup` suppresses.

### Phase A3 — Template fence hygiene (`quick_uvm/templates/*.j2`)
- A3.1 **(partly done)** Markers now isolated on their own lines (newline-gluing fixed).
  Decision: KEEP working-stub defaults *inside* fences (QuickUVM's philosophy); the
  default-vs-user comparison in `merge()` handles preservation correctly.
- A3.2 Jinja `pragma()` macro so all fences emit identically (defensive; prevents the
  newline-gluing class of bug from recurring in new templates).
- A3.3 **(new)** Fix global `{%-` over-trimming that collapses generated statements onto
  run-on lines — re-flow templates for readable, line-per-statement output.
- Acceptance: pristine tree → `status` reports zero modified sections; generated code is
  human-readable.

### Phase A4 — CLI honesty & ergonomics (`quick_uvm/cli.py`)
- A4.1 `generate` gains `--allow-drop` and `--no-backup`; non-zero exit on orphan by default.
- A4.2 Per-file report shows preserved/created/orphaned counts.
- A4.3 Real `status`: classify `untouched | user-modified | orphaned` + flag out-of-band
  edits to generated regions.
- A4.4 (optional) `diff` subcommand.

### Phase A5 — Marker coverage
- A5.1 Support `#`-style markers (regex `(//|#)`).
- A5.2 Fence the filelists `pkg.f`/`run.f` (`# pragma quickuvm custom extra_files`).
- A5.3 Audit fence completeness; add `new`/`extern bodies` hooks; component→fence table.

### Phase A6 — Docs
- A6.1 `docs/code_preservation.md` (marker syntax, fail-closed contract, flags, fence table).
- A6.2 `docs/comparison.md` (vs UVMF/Doulos/uvmgen/gen_uvm).
- A6.3 README preservation section update.

### Track A test matrix
| Scenario | Expected |
|---|---|
| edit fence → regen | preserved, file `updated` |
| rename/remove section, old code present | `MergeError` unless `--allow-drop`; backup written |
| delete `end` marker → regen | validation error pre-write |
| duplicate section name in file | deterministic, no cross-contamination |
| pristine tree → `status` | zero modified |
| edit non-fenced region → `status` | flagged out-of-band |
| add line in filelist fence → regen | preserved |
| `--no-backup` / `--allow-drop` | backup suppressed / proceeds past orphans |

---

# Track B — Close functional gaps (roadmap)

### Phase B1 — Register model (highest value for the SPI bridge)
- Consume existing `spi/reggen` output as source of truth.
- Templates: reg block (uvm_reg/uvm_reg_block), bus→reg adapter, reg predictor wiring,
  register test (hw_reset / bit-bash).
- `register_model:` config block in `models.py`.
- Acceptance: generated RAL compiles; hw_reset sequence runs against SPI registers.

### Phase B2 — Topology beyond single flat agent
- Sub-environments + explicit analysis/TLM connectivity; remove hardwired `agents[0]`
  assumption in `generator.py` and `sb_predictor.svh.j2`.

### Phase B3 — Parameterization & richer tests
- Interface/transaction `parameters:`; virtual-sequence / sequence-library config.

### Phase B4 — Run/regression infrastructure
- Xcelium-targeted run scripts + regression testlist (project is on Xcelium).

---

## Execution order & effort
1. **A0 → A1 → A2** (data-loss fix + backup) — small, high-value. **First.**
2. **A3 → A4** (fence hygiene + honest status).
3. **A5 → A6** (coverage + docs).
4. **B1 (RAL)** — separate scoping; largest functional payoff.

**Risk/rollback:** Track A changes are additive to a small, well-tested module; the
A2 backup is itself the rollback for any regen mishap. Land each phase behind passing
tests before the next.
