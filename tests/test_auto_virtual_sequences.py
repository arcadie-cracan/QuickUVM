"""Auto virtual-sequence default — the "add a vsqr as a habit" sane default.

With >=2 ACTIVE agents and no explicit `virtual_sequences:`, QuickUVM auto-scaffolds
env_vsqr + env_vseq_base + a default `<project>_vseq` (parallel by default) that fires
each active agent's base sequence, and the default test runs it on e.vsqr. Single-agent
benches, explicit-vseq benches, and `auto_virtual_sequences: false` get no auto layer.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    VseqConfig,
    VseqStep,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _agent(name, *, active=True):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        active=active,
        ports={
            "inputs": [PortConfig(name=f"{name}_in", width=8)],
            "outputs": [PortConfig(name=f"{name}_out", width=8)],
        },
    )


def _cfg(agents, *, virtual_sequences=None, auto=True, mode="parallel", tests=None):
    return ProjectConfig(
        project=ProjectMeta(name="sub"),
        dut=DutConfig(name="d", reset=""),
        agents=agents,
        tests=tests or [TConf(name="rand_test")],
        virtual_sequences=virtual_sequences or [],
        auto_virtual_sequences=auto,
        auto_vseq_mode=mode,
    )


def _gen(tmp_path, cfg):
    Generator(cfg).generate_all(tmp_path)
    return tmp_path


# ---- the property logic ----------------------------------------------------


def test_auto_triggers_for_two_active_agents():
    cfg = _cfg([_agent("a"), _agent("b")])
    assert cfg.auto_vseq_name == "d_vseq"
    vseqs = cfg.effective_virtual_sequences
    assert len(vseqs) == 1
    assert vseqs[0].name == "d_vseq"
    assert vseqs[0].mode == "parallel"
    assert [s.agent for s in vseqs[0].body] == ["a", "b"]
    assert [s.sequence for s in vseqs[0].body] == ["a_seq", "b_seq"]


def test_single_agent_no_auto():
    cfg = _cfg([_agent("a")])
    assert cfg.auto_vseq_name is None
    assert cfg.effective_virtual_sequences == []


def test_one_active_one_passive_no_auto():
    # only one DRIVING agent -> no vsqr needed
    cfg = _cfg([_agent("a"), _agent("mon", active=False)])
    assert cfg.auto_vseq_name is None
    assert cfg.effective_virtual_sequences == []


def test_passive_agents_excluded_from_body():
    cfg = _cfg([_agent("a"), _agent("b"), _agent("mon", active=False)])
    body = cfg.effective_virtual_sequences[0].body
    assert [s.agent for s in body] == ["a", "b"]  # mon excluded


def test_explicit_vseqs_win():
    explicit = VseqConfig(name="my_vseq", body=[VseqStep(agent="a", sequence="a_seq")])
    cfg = _cfg([_agent("a"), _agent("b")], virtual_sequences=[explicit])
    assert cfg.auto_vseq_name is None  # explicit suppresses the auto-default
    assert cfg.effective_virtual_sequences == [explicit]


def test_auto_off_no_layer():
    cfg = _cfg([_agent("a"), _agent("b")], auto=False)
    assert cfg.auto_vseq_name is None
    assert cfg.effective_virtual_sequences == []


def test_sequential_mode():
    cfg = _cfg([_agent("a"), _agent("b")], mode="sequential")
    assert cfg.effective_virtual_sequences[0].mode == "sequential"


# ---- generated artifacts ---------------------------------------------------


def test_auto_generates_vsqr_and_default_vseq(tmp_path):
    _gen(tmp_path, _cfg([_agent("a"), _agent("b")]))
    assert (tmp_path / "d_virtual_sequencer.svh").exists()
    assert (tmp_path / "d_base_vseq.svh").exists()
    vs = (tmp_path / "d_vseq.svh").read_text()
    assert "class d_vseq extends d_base_vseq;" in vs
    assert "fork" in vs  # parallel default
    assert "a_seq1.start(p_sequencer.a_sqr);" in vs
    assert "b_seq2.start(p_sequencer.b_sqr);" in vs


def test_default_test_runs_auto_vseq(tmp_path):
    _gen(tmp_path, _cfg([_agent("a"), _agent("b")]))
    test = (tmp_path / "rand_test.svh").read_text()
    assert "d_vseq seq;" in test
    assert "seq.start(e.vsqr);" in test


def test_auto_off_default_test_runs_primary_sequence(tmp_path):
    _gen(tmp_path, _cfg([_agent("a"), _agent("b")], auto=False))
    test = (tmp_path / "rand_test.svh").read_text()
    assert "a_seq seq;" in test
    assert "seq.start(e.a_agnt.sqr);" in test
    assert "e.vsqr" not in test


def test_sequential_auto_vseq_no_fork(tmp_path):
    _gen(tmp_path, _cfg([_agent("a"), _agent("b")], mode="sequential"))
    vs = (tmp_path / "d_vseq.svh").read_text()
    assert "fork" not in vs
    assert "a_seq1.start(p_sequencer.a_sqr);" in vs


def test_single_agent_test_unchanged(tmp_path):
    # the single-agent default launch is the primary sequence (byte-identical path)
    _gen(tmp_path, _cfg([_agent("a")]))
    assert not (tmp_path / "d_virtual_sequencer.svh").exists()
    test = (tmp_path / "rand_test.svh").read_text()
    assert "a_seq seq;" in test
    assert "seq.start(e.a_agnt.sqr);" in test


# ---- robustness (from review) ----------------------------------------------


def test_invalid_dut_name_rejected():
    # dut.name derives the auto vseq class name, so it must be an identifier
    with pytest.raises(Exception, match="legal SystemVerilog identifier"):
        DutConfig(name="my-proj")


def test_test_may_reference_auto_vseq_by_name(tmp_path):
    # a test can name the auto-default vseq explicitly (dut 'd' -> d_vseq)
    cfg = _cfg([_agent("a"), _agent("b")], tests=[TConf(name="t", vseq="d_vseq")])
    Generator(cfg).generate_all(tmp_path)
    test = (tmp_path / "t.svh").read_text()
    assert "d_vseq seq;" in test
    assert "seq.start(e.vsqr);" in test
