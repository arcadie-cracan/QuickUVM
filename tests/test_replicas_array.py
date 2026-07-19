"""I-9 — `replicas`: replicate one agent N times into ONE vectored DUT.

The alert_handler topology (one agent definition reused ~63 times: N alert lines into one
block). Distinct from C3 `instances` (different parameter values, each its own DUT): count
replicas are IDENTICAL and share one DUT, each bound to a slice of its vectored ports. Reuses
the C3 per-instance env/config/scoreboard machinery; the new part is the shared-vectored-DUT
wiring in tb_top. Proven end-to-end on examples/nchan.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    AnalysisConfig,
    DutConfig,
    InstanceConfig,
    ParamConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    ScoreboardSpec,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _agent(replicas=3, **kw):
    return AgentConfig(
        name="ch",
        interface="ch_if",
        sequence_item="ch_item",
        replicas=replicas,
        ports={
            "inputs": [PortConfig(name="d", width=1), PortConfig(name="v", width=1)],
            "outputs": [PortConfig(name="q", width=1, randomize=False)],
        },
        **kw,
    )


def _cfg(agent=None):
    return ProjectConfig(
        project=ProjectMeta(name="nchan"),
        dut=DutConfig(name="nchan", external_reset=True),
        agents=[agent or _agent()],
        tests=[TConf(name="t1", num_items=20)],
        analysis=AnalysisConfig(scoreboards=[ScoreboardSpec(name="sb", source="ch")]),
    )


# ---- wiring ----------------------------------------------------------------


def test_replicas_makes_n_interfaces_one_vectored_dut(tmp_path):
    Generator(_cfg()).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    # N interface instances
    for i in range(3):
        assert f"ch_if ch_{i}_if_inst" in top
    # exactly ONE DUT, with vectored (concatenated) port connections
    assert top.count("nchan dut_inst") == 1
    # one vectored DUT port per signal, each a concatenation of the N replica interfaces
    for sig in ("d", "q"):
        for i in range(3):
            assert f"ch_{i}_if_inst.{sig}" in top
    assert top.count(".d(") == 1 and top.count(".q(") == 1
    # NOT the C3 per-instance-DUT path
    assert "ch_0_dut" not in top


def test_replicas_makes_per_channel_scoreboards(tmp_path):
    Generator(_cfg()).generate_all(tmp_path)
    for i in range(3):
        assert (tmp_path / f"nchan_ch_{i}_scoreboard.svh").exists()
        assert (tmp_path / f"nchan_ch_{i}_reference_model.svh").exists()


def test_replicas_1_is_single_agent(tmp_path):
    """count: 1 (default) is the plain single-agent wiring — byte-identical elsewhere."""
    Generator(_cfg(_agent(replicas=1))).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "ch_if_inst" in top  # the single, unindexed interface
    assert "ch_0_if_inst" not in top
    assert not (tmp_path / "nchan_ch_0_scoreboard.svh").exists()


# ---- validation ------------------------------------------------------------


def test_replicas_zero_rejected():
    with pytest.raises(Exception, match="`replicas` must be >= 1"):
        _agent(replicas=0)


def test_replicas_with_instances_rejected():
    with pytest.raises(Exception, match="mutually exclusive with C3 `instances`"):
        _agent(
            replicas=3,
            parameters=[ParamConfig(name="W", default=8)],
            instances=[InstanceConfig(name="a", values={"W": 8})],
        )


def test_replicas_with_pure_responder_rejected():
    with pytest.raises(Exception, match="`replicas` is not yet supported with a PURE"):
        AgentConfig(
            name="ch",
            interface="ch_if",
            sequence_item="ch_item",
            replicas=3,
            mode="responder",
            request_valid="req",
            ports={
                "inputs": [PortConfig(name="rsp", width=1)],
                "outputs": [PortConfig(name="req", width=1, randomize=False)],
            },
        )


def _hybrid_replicas_agent():
    """count + a HYBRID (proactive responder) — the alert_handler alert-sender array."""
    return AgentConfig(
        name="sndr",
        interface="sndr_if",
        sequence_item="sndr_item",
        replicas=3,
        mode="responder",
        request_valid="ping",
        respond="on_request",
        proactive=True,
        ports={
            "inputs": [
                PortConfig(name="resp", width=1),
                PortConfig(name="alert", width=1),
            ],
            "outputs": [PortConfig(name="ping", width=1, randomize=False)],
        },
    )


def test_replicas_plus_hybrid_accepted_and_per_replica_liveness(tmp_path):
    """A HYBRID (proactive responder) IS allowed with count: N hybrid alert-senders into
    one DUT. Each replica gets its own responder sequencer with the request-drain liveness,
    so a dead responder in one channel is caught independently of the others."""
    cfg = ProjectConfig(
        project=ProjectMeta(name="aa"),
        dut=DutConfig(name="aa", external_reset=True),
        agents=[_hybrid_replicas_agent()],
        tests=[TConf(name="t1", num_items=20)],
    )
    Generator(cfg).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    sqr = (tmp_path / "sndr_sequencer.svh").read_text()
    # 3 hybrid replicas into one vectored DUT
    assert top.count("aa dut_inst") == 1
    for i in range(3):
        assert f"sndr_{i}_if_inst" in top
    # the (shared) sequencer carries the un-maskable per-replica drain liveness
    assert "request_fifo.used() != 0" in sqr
    assert "DEAD_RESPONDER" in sqr


# ---- fail-closed scope: reject out-of-scope combinations LOUDLY (not silent mis-gen) ----


def _proj(**kw):
    base = dict(
        project=ProjectMeta(name="n"),
        dut=DutConfig(name="n", external_reset=True),
        agents=[_agent()],
        tests=[TConf(name="t")],
    )
    base.update(kw)
    return ProjectConfig(**base)


def test_replicas_requires_external_reset():
    with pytest.raises(Exception, match="needs `reset:"):
        _proj(dut=DutConfig(name="n", external_reset=False))


def test_replicas_rejects_second_agent():
    other = AgentConfig(
        name="b",
        interface="b_if",
        sequence_item="b_item",
        ports={"inputs": [PortConfig(name="x", width=1)]},
    )
    with pytest.raises(Exception, match="must be the SOLE agent"):
        _proj(agents=[_agent(), other])


def test_replicas_rejects_coverage():
    with pytest.raises(Exception, match="does not yet wire coverage"):
        _proj(analysis=AnalysisConfig(coverage=["ch"]))


def test_replicas_rejects_windowed_scoreboard():
    from quick_uvm.models import WindowSpec

    sb = ScoreboardSpec(
        name="sb", source="ch", window=WindowSpec(boundary="q", length=4)
    )
    with pytest.raises(Exception, match="must be a plain single-stream scoreboard"):
        _proj(analysis=AnalysisConfig(scoreboards=[sb]))
