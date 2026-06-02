# Jinja template style — the bridge

Conventions for `quick_uvm/templates/*.j2`. These are **not preferences** — most are
regression-prevention rules with scars behind them: a template defect becomes an *output*
defect shipped to every user. Several are pinned by tests (`tests/test_template_markers.py`,
`tests/test_generator.py`); keep them green.

## The cardinal rules (learned the hard way)

1. **No `{%-` / `-%}` whitespace left-strips.** They caused QuickUVM's worst latent bug:
   the strip ate the newline before pragma markers, gluing generated code onto marker and
   `//` comment lines — in the monitor it *silently commented out the DUT-sampling
   assignments*. Rely on `trim_blocks` + `lstrip_blocks` (set in the environment) for
   whitespace; do not hand-trim with `-`.

2. **Pragma markers stand alone.** Every `// pragma quickuvm custom <name> begin|end`
   must be on its own line, emitted through the shared `pragma()` macro — never inlined
   next to generated code. This is what makes the fail-closed merge reliable
   (see [`code_preservation.md`](code_preservation.md)).

3. **One statement per line.** No run-on output. Generated SV must satisfy
   [`style_systemverilog.md`](style_systemverilog.md) (100-col, readable) — and it's the
   template's job to produce that, since Verible gates the result in CI.

4. **Deterministic output.** Iterate config collections in a stable order; don't depend on
   dict insertion quirks. Same config in → byte-identical output (regen diffs must be
   reviewable; this is also asserted by idempotency tests).

## Hygiene

- Prefer a single `pragma()` macro / shared partials over copy-pasted fences, so the
  marker format can't drift between templates.
- Keep generated banner headers consistent across all templates.
- When adding a template, add it to the marker/idempotency test coverage.
- Filelists (`pkg.f`, `run.f`) are templates too — the same run-on bug once produced
  `tb_pkg.svreg_if.sv`; keep entries newline-separated.

## Why this lives in its own doc

Template bugs are invisible until you read (or simulate) the output, so the rules that
prevent them deserve to be explicit and testable rather than tribal knowledge.
