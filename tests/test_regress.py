"""R1 — the regression + coverage runner (opt-in `regress:` block)."""

import pytest
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_BASE = {
    "project": {"name": "r_tb", "author": "a@b.c"},
    "dut": {"name": "r", "clock": "clk", "reset": "", "combinational": True},
    "agents": [
        {
            "name": "io",
            "interface": "io_if",
            "sequence_item": "io_seq_item",
            "ports": {
                "inputs": [{"name": "a", "width": 8, "randomize": True}],
                "outputs": [{"name": "y", "width": 8}],
            },
        }
    ],
    "tests": [{"name": "rand_test"}],
}


def _gen(tmp_path, **over):
    cfg = ProjectConfig.model_validate({**_BASE, **over})
    Generator(cfg).generate_all(tmp_path, backup=False)
    return cfg


def test_absent_emits_no_makefile(tmp_path):
    """Opt-in: no `regress:` => no Makefile => existing benches byte-identical."""
    _gen(tmp_path)
    assert not (tmp_path / "Makefile").exists()


def test_present_emits_makefile(tmp_path):
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "JOBS      ?= rand_test:1" in mk
    assert "TEST      ?= rand_test" in mk
    # Drives the REAL-RTL filelist, not the generated DUT stub.
    assert "FILELIST ?= ../sim/xrun.f" in mk


def test_seeds_and_per_test_override(tmp_path):
    _gen(
        tmp_path,
        regress={"seeds": 2},
        tests=[{"name": "rand_test", "seeds": 5}, {"name": "smoke_test"}],
    )
    mk = (tmp_path / "Makefile").read_text()
    # rand_test overrides; smoke_test inherits regress.seeds.
    assert "JOBS      ?= rand_test:5 smoke_test:2" in mk


def test_testlist_includes_ral_and_csr_tests(tmp_path):
    """The RAL reg_test's CLASS is the bare `reg_test` — only its FILE is prefixed.

    A testlist that emitted `r_reg_test` would hand +UVM_TESTNAME an unregistered
    name and the run would die in the UVM factory.
    """
    cfg = _gen(
        tmp_path,
        regress={},
        register_model={
            "package": "r_ral_pkg",
            "block": "r_reg_block",
            "bus_agent": "io",
            "csr_tests": ["hw_reset", "rw"],
        },
    )
    names = [j["name"] for j in cfg.regress_jobs]
    assert names == ["rand_test", "reg_test", "r_csr_hw_reset_test", "r_csr_rw_test"]
    assert "r_reg_test" not in names
    mk = (tmp_path / "Makefile").read_text()
    assert "reg_test:1" in mk and "r_csr_rw_test:1" in mk


def test_coverage_off_omits_the_merge_flow(tmp_path):
    """No half-wired coverage: with coverage off there is no `cov` target and no
    dangling -coverage flags referencing undefined COVWORK/COVSCOPE vars."""
    _gen(tmp_path, regress={"coverage": False})
    mk = (tmp_path / "Makefile").read_text()
    assert "imc -exec" not in mk
    assert "-coverage all" not in mk
    assert "COVWORK" not in mk


def test_coverage_on_emits_imc_merge_and_report(tmp_path):
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "-coverage all" in mk
    # imc's -batch/-exec are mutually exclusive; a command file passed to -exec alone.
    assert "imc -exec" in mk
    assert "imc -batch" not in mk
    # Text report needs the legacy `report -summary -text` (report_metrics is HTML-only).
    assert "report -summary -text" in mk


def test_verdict_does_not_trust_the_exit_code(tmp_path):
    """xrun exits 0 even with UVM_ERRORs, so the verdict MUST parse the severity
    block, and must NOT parse the (always-zero) report-catcher count."""
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "Report counts by severity" in mk
    # `$$finish` is make-escaping: the recipe hands the shell a literal `$finish`.
    assert "grep -qF 'Simulation complete via $$finish'" in mk
    # The catcher count is named in a comment (explaining why it is a trap), but no
    # recipe line may actually parse it — that is what marks failing runs PASS.
    recipes = [ln for ln in mk.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("Number of caught" in ln for ln in recipes)


def test_run_clears_stale_artifacts_first(tmp_path):
    """If xrun fails to LAUNCH it writes no log. Unless the previous run's log is
    cleared first, the verdict parses THAT and reports its stale PASS."""
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    run1 = mk.split("run1:")[1].split("\nrun:")[0]
    assert "rm -f" in run1 and "sim.log" in run1
    # ...and the clear must precede the xrun invocation.
    assert run1.index("rm -f") < run1.index("xrun -R")


def test_regress_drops_previous_coverage_dbs(tmp_path):
    """Merging every DB ever written would fold in an older regression's runs — of
    possibly older code — and report coverage this run never achieved."""
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "rm -rf $(COVWORK)/$(COVSCOPE)/*/" in mk


def test_empty_joblist_cannot_report_green(tmp_path):
    """xargs without -r would invoke run1 once with the default TEST/SEED, so a
    regression that ran none of its tests would report '1/1 passed'."""
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "xargs -r " in mk
    assert "NO RUNS" in mk


def test_cov_zero_skips_coverage_instead_of_aborting(tmp_path):
    """`make regress COV=0` is advertised as a quick pass — it must not die in `cov`
    with 'no coverage runs'."""
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert 'if [ "$(COV)" = 1 ]; then $(MAKE) --no-print-directory cov; fi' in mk


def test_snapshot_rebuilds_when_sources_change(tmp_path):
    """The elaboration stamp MUST depend on the filelist's sources.

    Without this, `make regress` reuses a stale snapshot after an RTL edit and
    reports PASS for code it never compiled — a false green, the worst outcome a
    regression runner can produce.
    """
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "SRCS :=" in mk
    assert "$(ELAB_OK): $(FILELIST) $(SRCS)" in mk


def test_seeds_override_is_a_real_variable(tmp_path):
    """`make regress SEEDS=10` must actually override the per-test counts — the
    READMEs advertise it, and a documented flag that silently does nothing is worse
    than no flag."""
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "SEEDS     ?=" in mk
    assert 'if [ -n "$(SEEDS)" ]; then n=$(SEEDS); fi' in mk


def test_seed_is_explicit_never_random(tmp_path):
    """A regression you cannot replay is not a regression."""
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()
    assert "-svseed $(SEED)" in mk
    assert "-svseed random" not in mk
    assert "reproduce: make run TEST=%s SEED=%s" in mk


# --- fail-closed validation -------------------------------------------------


def test_rejects_zero_seeds():
    with pytest.raises(ValidationError, match="seeds must be >= 1"):
        ProjectConfig.model_validate({**_BASE, "regress": {"seeds": 0}})


def test_rejects_empty_testlist():
    """A regression that runs nothing must not report success."""
    with pytest.raises(ValidationError, match="at least one runnable test"):
        ProjectConfig.model_validate({**_BASE, "regress": {}, "tests": []})


def test_empty_tests_without_regress_still_generates(tmp_path):
    """`tests: []` is a legal config. R1 must not crash a bench that doesn't use it —
    that would break the opt-in guarantee for configs that never asked for R1."""
    _gen(tmp_path, tests=[])
    assert not (tmp_path / "Makefile").exists()


def test_rejects_empty_filelist():
    with pytest.raises(ValidationError, match="non-empty path"):
        ProjectConfig.model_validate({**_BASE, "regress": {"filelist": "  "}})


def test_rejects_unknown_simulator():
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({**_BASE, "regress": {"simulator": "questa"}})


def test_rejects_duplicate_test_name_colliding_with_reg_test():
    """A user test literally named `reg_test` would collide with the RAL one."""
    with pytest.raises(ValidationError, match="duplicate \\+UVM_TESTNAME"):
        ProjectConfig.model_validate(
            {
                **_BASE,
                "regress": {},
                "tests": [{"name": "reg_test"}],
                "register_model": {
                    "package": "p",
                    "block": "b",
                    "bus_agent": "io",
                },
            }
        )


def test_snapshot_depends_on_included_class_files(tmp_path):
    """The rebuild trigger must cover `.svh` class files, not just the filelist.

    The filelist names only COMPILATION UNITS (packages, interfaces, modules). Every
    UVM class — driver, monitor, predictor, reference model, scoreboard, sequences,
    tests — is a `.svh` `include`d by the tb package, so none of them appear in it.
    Deriving the snapshot's prerequisites from the filelist alone therefore leaves
    them untracked, and `make regress` re-runs a STALE snapshot and verdicts PASS on
    code it never compiled. Caught for real on the spi bench: a mutated reference
    model reported 8/8 PASS with a warm snapshot, 7/8 (correctly red) when forced to
    rebuild. The `.svh` files live in the `+incdir` dirs by construction.
    """
    _gen(tmp_path, regress={})
    mk = (tmp_path / "Makefile").read_text()

    assert "INCDIRS" in mk, "the include dirs are not extracted from the filelist"
    # NB the grep pattern bracket-escapes the plus: `[+]incdir[+]`, not `+incdir+`.
    assert "incdir" in mk, "INCDIRS must be derived from the filelist's +incdir entries"
    assert "*.svh" in mk, (
        "the .svh class files are not tracked as snapshot prerequisites"
    )
    assert "SRCS += $(wildcard $(addsuffix /*.svh,$(INCDIRS)))" in mk

    # ...and they must actually reach the snapshot rule, not just be computed.
    assert "$(ELAB_OK): $(FILELIST) $(SRCS)" in mk


def test_srcs_drops_whole_option_lines_not_words(tmp_path):
    """`-top tb_top` must not leave `tb_top` looking like a source file.

    The filter is line-based for exactly this reason: an option's ARGUMENT is not a
    source, and a bogus prerequisite with no rule to build it aborts make.
    """
    mk = (_gen(tmp_path, regress={}), (tmp_path / "Makefile").read_text())[1]
    # the source list drops any line STARTING with - or + (the option's args go with it)
    assert "grep -vE '^[[:space:]]*[-+]'" in mk
