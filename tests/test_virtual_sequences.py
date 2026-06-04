"""C2 — virtual sequencer + virtual sequences (opt-in virtual_sequences).

Declaring `virtual_sequences:` generates env_vsqr (handles to each active agent's
sequencer), env_vseq_base (p_sequencer = vsqr), and one class per vsequence whose
body starts per-agent sub-sequences (sequential or fork/join). A test's `vseq:`
selector runs a virtual sequence on e.vsqr. Byte-identical when absent.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    SequenceConfig,
    VseqConfig,
    VseqStep,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _two_agents():
    wr = AgentConfig(
        name="wr",
        interface="wr_if",
        sequence_item="wr_seq_item",
        ports={
            "inputs": [PortConfig(name="wr_data", width=8)],
            "outputs": [PortConfig(name="full", width=1)],
        },
        sequences=[
            SequenceConfig(name="wr_rand", kind="random", count=32),
            SequenceConfig(
                name="wr_walk", kind="incrementing", count=16, field="wr_data"
            ),
        ],
    )
    rd = AgentConfig(
        name="rd",
        interface="rd_if",
        sequence_item="rd_seq_item",
        ports={
            "inputs": [PortConfig(name="rd_en", width=1)],
            "outputs": [PortConfig(name="rd_data", width=8)],
        },
        sequences=[SequenceConfig(name="rd_rand", kind="random", count=32)],
    )
    return [wr, rd]


def _cfg(virtual_sequences=None, tests=None, agents=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="fifo"),
        agents=agents or _two_agents(),
        tests=tests or [TConf(name="t1")],
        virtual_sequences=virtual_sequences or [],
    )


_SMOKE = VseqConfig(
    name="smoke_vseq",
    mode="sequential",
    body=[
        VseqStep(agent="wr", sequence="wr_walk"),
        VseqStep(agent="rd", sequence="rd_rand"),
    ],
)
_STRESS = VseqConfig(
    name="stress_vseq",
    mode="parallel",
    body=[
        VseqStep(agent="wr", sequence="wr_rand"),
        VseqStep(agent="rd", sequence="rd_rand"),
    ],
)


def _gen(tmp_path, virtual_sequences=None, tests=None):
    Generator(_cfg(virtual_sequences, tests)).generate_all(tmp_path)
    return tmp_path


# ---- generated vsqr / vseq -------------------------------------------------


def test_vsqr_has_sequencer_handles(tmp_path):
    _gen(tmp_path, [_SMOKE])
    vsqr = (tmp_path / "fifo_virtual_sequencer.svh").read_text()
    assert "class fifo_virtual_sequencer extends uvm_sequencer;" in vsqr
    assert "wr_sequencer wr_sqr;" in vsqr
    assert "rd_sequencer rd_sqr;" in vsqr


def test_vseq_base_declares_p_sequencer(tmp_path):
    _gen(tmp_path, [_SMOKE])
    base = (tmp_path / "fifo_base_vseq.svh").read_text()
    assert "class fifo_base_vseq extends uvm_sequence #(uvm_sequence_item);" in base
    assert "`uvm_declare_p_sequencer(fifo_virtual_sequencer)" in base


def test_sequential_vseq_body(tmp_path):
    _gen(tmp_path, [_SMOKE])
    vs = (tmp_path / "smoke_vseq.svh").read_text()
    assert "class smoke_vseq extends fifo_base_vseq;" in vs
    assert "wr_seq1.start(p_sequencer.wr_sqr);" in vs
    assert "rd_seq2.start(p_sequencer.rd_sqr);" in vs
    assert "fork" not in vs  # sequential


def test_parallel_vseq_uses_fork_join(tmp_path):
    _gen(tmp_path, [_STRESS])
    vs = (tmp_path / "stress_vseq.svh").read_text()
    assert "fork" in vs
    assert "join" in vs
    assert "wr_seq1.start(p_sequencer.wr_sqr);" in vs


def test_env_wires_vsqr(tmp_path):
    _gen(tmp_path, [_SMOKE])
    env = (tmp_path / "fifo_env.svh").read_text()
    assert "fifo_virtual_sequencer vsqr;" in env
    assert 'vsqr = fifo_virtual_sequencer::type_id::create("vsqr", this);' in env
    assert "vsqr.wr_sqr = wr_agnt.sqr;" in env
    assert "vsqr.rd_sqr = rd_agnt.sqr;" in env


def test_tb_pkg_includes_vseq_files(tmp_path):
    _gen(tmp_path, [_SMOKE, _STRESS])
    pkg = (tmp_path / "fifo_tb_pkg.sv").read_text()
    assert '`include "fifo_virtual_sequencer.svh"' in pkg
    assert '`include "fifo_base_vseq.svh"' in pkg
    assert '`include "smoke_vseq.svh"' in pkg
    assert '`include "stress_vseq.svh"' in pkg


def test_test_runs_vseq_on_vsqr(tmp_path):
    _gen(tmp_path, [_SMOKE], tests=[TConf(name="smoke", vseq="smoke_vseq")])
    test = (tmp_path / "smoke.svh").read_text()
    assert "smoke_vseq seq;" in test
    assert "seq.start(e.vsqr);" in test


# ---- byte-identical when absent --------------------------------------------


def test_no_vsqr_when_auto_off(tmp_path):
    # 2 agents but auto-vsqr disabled and no explicit vseqs -> no virtual-seq layer
    cfg = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="fifo"),
        agents=_two_agents(),
        tests=[TConf(name="t1")],
        auto_virtual_sequences=False,
    )
    Generator(cfg).generate_all(tmp_path)
    assert not (tmp_path / "fifo_virtual_sequencer.svh").exists()
    assert not (tmp_path / "fifo_base_vseq.svh").exists()
    env = (tmp_path / "fifo_env.svh").read_text()
    assert "vsqr" not in env


# ---- multi-agent top.sv connects ALL agents --------------------------------


def test_top_connects_all_agents(tmp_path):
    # a registered 2-agent DUT: the DUT connection must wire BOTH interfaces
    Generator(_cfg([_SMOKE])).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert ".full(wr_if_inst.full)" in top
    assert ".wr_data(wr_if_inst.wr_data)" in top
    assert ".rd_data(rd_if_inst.rd_data)" in top  # second agent — was missing before
    assert ".rd_en(rd_if_inst.rd_en)" in top
    assert ".clk(clk)" in top


# ---- validation ------------------------------------------------------------


def test_duplicate_vseq_name_rejected():
    with pytest.raises(Exception, match="duplicate vsequence name"):
        _cfg(
            [
                _SMOKE,
                VseqConfig(
                    name="smoke_vseq", body=[VseqStep(agent="wr", sequence="wr_rand")]
                ),
            ]
        )


def test_reserved_vseq_name_rejected():
    with pytest.raises(Exception, match="reserved"):
        _cfg(
            [
                VseqConfig(
                    name="env_vseq_base",
                    body=[VseqStep(agent="wr", sequence="wr_rand")],
                )
            ]
        )


def test_vseq_unknown_agent_rejected():
    with pytest.raises(Exception, match="unknown agent"):
        _cfg([VseqConfig(name="v", body=[VseqStep(agent="nope", sequence="x")])])


def test_vseq_unknown_sequence_rejected():
    with pytest.raises(Exception, match="not a library sequence"):
        _cfg([VseqConfig(name="v", body=[VseqStep(agent="wr", sequence="ghost")])])


def test_vseq_step_can_use_default_sequence():
    # the default <agent>_seq is always a valid step target
    _cfg([VseqConfig(name="v", body=[VseqStep(agent="wr", sequence="wr_seq")])])


def test_vseq_passive_agent_rejected():
    wr = AgentConfig(
        name="wr",
        interface="wr_if",
        sequence_item="wr_seq_item",
        active=False,
        ports={"inputs": [PortConfig(name="d", width=8)], "outputs": []},
        sequences=[SequenceConfig(name="wr_rand", kind="random")],
    )
    rd = AgentConfig(
        name="rd",
        interface="rd_if",
        sequence_item="rd_seq_item",
        ports={"inputs": [PortConfig(name="d", width=8)], "outputs": []},
    )
    with pytest.raises(Exception, match="passive agent"):
        _cfg(
            agents=[wr, rd],
            virtual_sequences=[
                VseqConfig(name="v", body=[VseqStep(agent="wr", sequence="wr_rand")])
            ],
        )


def test_empty_vseq_body_rejected():
    with pytest.raises(Exception, match="at least one step"):
        VseqConfig(name="v", body=[])


def test_test_vseq_and_sequence_mutually_exclusive():
    from quick_uvm.models import TestSeqSel

    with pytest.raises(Exception, match="not both"):
        TConf(name="t", vseq="v", sequence=TestSeqSel(agent="wr", name="wr_rand"))


def test_test_unknown_vseq_rejected():
    with pytest.raises(Exception, match="not a declared vsequence"):
        _cfg([_SMOKE], tests=[TConf(name="t", vseq="ghost")])
