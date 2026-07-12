#!/usr/bin/env bash
#
# The Xcelium gate — compile every example's REAL bench and report what breaks.
#
# WHY THIS IS A SCRIPT AND NOT A CI JOB
# -------------------------------------
# QuickUVM's CI runs on GitHub-hosted runners, which have no Cadence licence, so
# "Xcelium in CI" is not available to us. The free alternatives were measured
# against the one bug that motivated this gate (`<agent>_cov <agent>_cov;` — a
# member shadowing its own type, then used as `<agent>_cov::type_id::create()`):
#
#   xrun -compile        exit 1 on the bug, 0 on the fix   <- the only discriminator
#   verible-verilog-lint exit 0 on both                    <- blind (this is CI today)
#   verilator --lint-only exit 0 on both                   <- also blind
#   iverilog -g2012      errors on the CLEAN code too      <- false-positive machine
#
# So a free-simulator lane cannot substitute. Two things close the gap instead:
#
#   1. tests/test_no_type_shadowing.py — a targeted static check for that bug CLASS.
#      Runs free on hosted CI, no licence. ENFORCED.
#   2. this script — the real compiler, over every example. Catches bug classes we
#      have not thought of yet. NOT enforceable by CI: run it before you push.
#
# `xrun -compile` parses and type-checks without elaborating or simulating, so it is
# seconds per example, not minutes.
#
# Usage:  scripts/xrun_gate.sh [example ...]      (default: every example with a sim/)
#
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2
repo="$PWD"

if ! command -v xrun >/dev/null 2>&1; then
  echo "xrun not found — this gate needs Xcelium. (CI cannot run it; that is expected.)" >&2
  exit 2
fi

if [ $# -gt 0 ]; then
  examples=("$@")
else
  examples=()
  for f in examples/*/sim/xrun.f; do
    [ -e "$f" ] || continue
    examples+=("$(basename "$(dirname "$(dirname "$f")")")")
  done
fi

pass=0
fail=0
failed=()

for ex in "${examples[@]}"; do
  simdir="$repo/examples/$ex/sim"
  if [ ! -f "$simdir/xrun.f" ]; then
    echo "  SKIP  $ex (no sim/xrun.f)"
    continue
  fi
  log="$simdir/.xrun_gate.log"
  if (cd "$simdir" && xrun -compile -f xrun.f) > "$log" 2>&1; then
    printf "  PASS  %s\n" "$ex"
    pass=$((pass + 1))
    rm -f "$log"
  else
    printf "  FAIL  %s\n" "$ex"
    # The compile errors are what we came for — show them.
    grep -E '^\s*(xmvlog|xmelab|xrun):\s*\*[EF],' "$log" | head -5 | sed 's/^/          /'
    printf "          log: examples/%s/sim/.xrun_gate.log\n" "$ex"
    fail=$((fail + 1))
    failed+=("$ex")
  fi
done

echo "  ---- $pass passed, $fail failed"
if [ "$fail" -gt 0 ]; then
  echo "  FAILED: ${failed[*]}"
  exit 1
fi
