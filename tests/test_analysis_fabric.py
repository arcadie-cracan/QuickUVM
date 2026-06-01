"""Phase C1 (MVP per-agent routing) — opt-in declarative analysis fabric.

The `analysis:` block lets the user route a coverage collector per agent and bind
each scoreboard to a source agent. When omitted, the env keeps the legacy
single-stream wiring (verified byte-identical elsewhere). Fixes the bug where
non-primary agents were instantiated but never connected.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    AnalysisConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    ScoreboardSpec,
    TestConfig as TConf,
)


def _ag(n):
    return AgentConfig(
        name=n, interface=f"{n}_if", transaction=f"{n}_trans",
        ports={"outputs": [PortConfig(name="dout", width=8, randomize=False)],
               "inputs": [PortConfig(name="din", width=8)]},
    )


def _cfg(agents, analysis=None):
    return ProjectConfig(project=ProjectMeta(name="t"), dut=DutConfig(name="d"),
                         agents=agents, tests=[TConf(name="t1")], analysis=analysis)


# ---- default (no analysis) keeps legacy single-stream wiring --------------

def test_default_env_is_legacy_single_stream(tmp_path):
    Generator(_cfg([_ag("reg")])).generate_all(tmp_path)
    e = (tmp_path / "env.svh").read_text()
    assert "tb_scoreboard sbd;" in e
    assert "reg_cover cov;" in e
    assert "reg_agnt.ap.connect(sbd.axp);" in e
    assert "reg_agnt.ap.connect(cov.analysis_export);" in e


# ---- analysis block: per-agent coverage + scoreboard source ----------------

def test_analysis_wires_per_agent_coverage_and_scoreboard(tmp_path):
    cfg = _cfg(
        [_ag("drv"), _ag("mon")],
        AnalysisConfig(coverage=["drv", "mon"],
                       scoreboards=[ScoreboardSpec(name="sbd", source="drv")]),
    )
    Generator(cfg).generate_all(tmp_path)
    e = (tmp_path / "env.svh").read_text()
    # per-agent coverage collectors
    assert "drv_cover drv_cov;" in e
    assert "mon_cover mon_cov;" in e
    assert "drv_agnt.ap.connect(drv_cov.analysis_export);" in e
    assert "mon_agnt.ap.connect(mon_cov.analysis_export);" in e
    # scoreboard bound to its source agent
    assert "tb_scoreboard sbd;" in e
    assert "drv_agnt.ap.connect(sbd.axp);" in e
    # legacy primary-only comment must be gone in the data-driven path
    assert "Primary agent" not in e


def test_agent_absent_from_analysis_is_not_connected(tmp_path):
    # 'mon' is instantiated but intentionally routed nowhere.
    cfg = _cfg(
        [_ag("drv"), _ag("mon")],
        AnalysisConfig(coverage=["drv"],
                       scoreboards=[ScoreboardSpec(name="sbd", source="drv")]),
    )
    Generator(cfg).generate_all(tmp_path)
    e = (tmp_path / "env.svh").read_text()
    assert "mon_agent  mon_agnt;" in e          # still instantiated
    assert "mon_cov" not in e                    # but no coverage
    assert "mon_agnt.ap.connect" not in e        # and no connection


# ---- validation ------------------------------------------------------------

def test_unknown_coverage_agent_rejected():
    with pytest.raises(Exception, match="unknown agent 'nope'"):
        _cfg([_ag("reg")], AnalysisConfig(coverage=["nope"]))


def test_unknown_scoreboard_source_rejected():
    with pytest.raises(Exception, match="unknown source agent 'nope'"):
        _cfg([_ag("reg")], AnalysisConfig(scoreboards=[ScoreboardSpec(name="s", source="nope")]))


def test_duplicate_scoreboard_names_rejected():
    with pytest.raises(Exception, match="scoreboards names must be unique"):
        _cfg([_ag("reg")], AnalysisConfig(
            scoreboards=[ScoreboardSpec(name="s", source="reg"),
                         ScoreboardSpec(name="s", source="reg")]))
