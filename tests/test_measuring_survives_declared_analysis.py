"""Measuring must survive the switch to declared analysis (issue #115).

`analysis:` is presence-switched: omit it and the env wires one scoreboard AND one
coverage collector to the primary agent; declare it and you get exactly what is listed.
So adding a FIRST scoreboard removes a collector that was already there — silently. The
bench still checks correctly, it just stops measuring: `<agent>_cov.svh` is still
generated and still compiled into the tb package, merely never connected, so its
covergroup never samples and the report shows nothing.

This is the UNCHECKED_AGENT hole seen from the other side. That guard, and the
UNFILLED_PREDICTOR fatal, cover every way inference can make a bench pass FALSELY;
neither covers inference that makes a bench silently WEAKER. Same remedy at
proportionate severity — a uvm_warning, not a fatal: an unmeasured bench is weaker,
not wrong.

The escape hatch is what keeps it from being permanent noise: writing `coverage: []`
says "measure nothing" deliberately and silences it. That distinction only exists
because AnalysisConfig records whether the key was WRITTEN, since absent and `[]` are
indistinguishable after validation.
"""

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_AGENT = {
    "name": "pkt",
    "interface": "pkt_if",
    "sequence_item": "pkt_item",
    "ports": {
        "inputs": [{"name": "in_valid", "width": 1}],
        "outputs": [{"name": "out_valid", "width": 1}],
    },
}
_SB = {"name": "sbd", "source": "pkt"}


def _cfg(analysis=None):
    data = {
        "project": {"name": "y"},
        "dut": {"name": "y", "clock": "clk", "reset": "rst_n"},
        "agents": [_AGENT],
    }
    if analysis is not None:
        data["analysis"] = analysis
    return ProjectConfig.model_validate(data)


def _env(cfg):
    g = Generator(cfg)
    spec = next(s for s in g.files_to_generate() if s.output.endswith("_env.svh"))
    return g.render(spec)


# --- the property ----------------------------------------------------------------


def test_implicit_wiring_is_never_flagged():
    """No `analysis:` at all: the implicit wiring IS the coverage. Nothing was lost."""
    assert _cfg().uncovered_agents == []


def test_declaring_a_scoreboard_without_coverage_is_flagged():
    """The reported case: adding a scoreboard drops the collector you already had."""
    assert _cfg({"scoreboards": [_SB]}).uncovered_agents == ["pkt"]


def test_explicit_empty_coverage_is_deliberate():
    """`coverage: []` means "measure nothing" — the escape hatch, so this is not noise."""
    assert _cfg({"coverage": [], "scoreboards": [_SB]}).uncovered_agents == []


def test_declared_coverage_is_not_flagged():
    assert _cfg({"coverage": ["pkt"], "scoreboards": [_SB]}).uncovered_agents == []


def test_empty_analysis_block_is_not_flagged():
    """`analysis: {}` declares no scoreboard either — nothing was traded for coverage."""
    assert _cfg({}).uncovered_agents == []


def test_scoped_to_what_was_lost_not_to_an_opinion():
    """The implicit wiring only ever covered the PRIMARY agent, so only it can be
    listed. Warning about a second uncovered agent would be a new policy, not this
    one — that axis belongs to UNCHECKED_AGENT."""
    # distinct port names: the flat tb_top binds every agent port to one DUT port
    second = {
        "name": "rsp",
        "interface": "rsp_if",
        "sequence_item": "rsp_item",
        "ports": {
            "inputs": [{"name": "rsp_in", "width": 1}],
            "outputs": [{"name": "rsp_out", "width": 1}],
        },
    }
    cfg = ProjectConfig.model_validate(
        {
            "project": {"name": "y"},
            "dut": {"name": "y", "clock": "clk", "reset": "rst_n"},
            "agents": [_AGENT, second],
            "analysis": {"scoreboards": [_SB]},
        }
    )
    assert cfg.uncovered_agents == ["pkt"]


# --- the generated guard ---------------------------------------------------------


def test_the_warning_reaches_the_generated_env():
    env = _env(_cfg({"scoreboards": [_SB]}))
    assert "UNCOVERED_AGENT" in env
    assert "pkt_cov" in env  # the class it names is the one that is not connected


def test_no_warning_and_coverage_IS_wired_when_declared():
    env = _env(_cfg({"coverage": ["pkt"], "scoreboards": [_SB]}))
    assert "UNCOVERED_AGENT" not in env
    # declared coverage instantiates <agent>_cov_h (NOT `cov`, which is the implicit name)
    assert "pkt_cov_h.analysis_export" in env


def test_implicit_env_wires_cov_and_stays_silent():
    env = _env(_cfg())
    assert "UNCOVERED_AGENT" not in env
    assert "cov.analysis_export" in env


def test_guard_function_is_absent_when_nothing_to_report():
    """A bench with no guard must not carry an empty end_of_elaboration_phase — that
    would be byte-visible in every clean example."""
    env = _env(_cfg({"coverage": ["pkt"], "scoreboards": [_SB]}))
    assert "end_of_elaboration_phase" not in env
