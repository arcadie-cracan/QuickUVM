"""Hybrid (initiator + responder) agent — `proactive: true` on an on_request responder.

An alert-sender answers the DUT's pings (reactive) AND spontaneously raises alerts
(proactive). The agent stays a responder — the env still forks its responder sequence —
but it ALSO joins the stimulus agents, so the test starts a proactive sequence on the same
sequencer (UVM arbitrates the two). Its liveness is the un-maskable request-FIFO drain, NOT
the driver's DEAD_RESPONDER drive count (which the proactive stimulus inflates). Proven
end-to-end on examples/hybrid_alert.
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
    SequenceConfig,
)
from quick_uvm.models import (
    TestConfig as TConf,
)
from quick_uvm.models import (
    TestSeqSel as TSeq,
)


def _hybrid_agent(proactive=True, respond="on_request"):
    return AgentConfig(
        name="sndr",
        interface="sndr_if",
        sequence_item="sndr_item",
        mode="responder",
        request_valid="ping",
        respond=respond,
        proactive=proactive,
        ports={
            "inputs": [
                PortConfig(name="resp", width=1),
                PortConfig(name="alert", width=1),
            ],
            "outputs": [PortConfig(name="ping", width=1, randomize=False)],
        },
        sequences=[SequenceConfig(name="alert_raise_seq", kind="directed")],
    )


def _cfg(agent=None, test=None):
    agent = agent or _hybrid_agent()
    test = test or TConf(name="t1", sequence=TSeq(agent="sndr", name="alert_raise_seq"))
    return ProjectConfig(
        project=ProjectMeta(name="hyb"),
        dut=DutConfig(name="dev"),
        agents=[agent],
        tests=[test],
        analysis=AnalysisConfig(scoreboards=[ScoreboardSpec(name="sb", source="sndr")]),
    )


# ---- wiring: proactive responder is BOTH forked-responder AND stimulus target ----------


def test_proactive_responder_gets_test_stimulus(tmp_path):
    """The test starts a proactive sequence on the hybrid's sequencer (it joined the
    stimulus agents), while the agent still forks its responder sequence."""
    Generator(_cfg()).generate_all(tmp_path)
    test = (tmp_path / "t1.svh").read_text()
    agent = (tmp_path / "sndr_agent.svh").read_text()
    assert "seq.start(e.sndr_agnt.sqr)" in test  # proactive stimulus on the sequencer
    assert "sndr_responder_seq responder" in agent  # ...AND the responder still forked


def test_proactive_responder_has_undmaskable_drain_liveness(tmp_path):
    """The sequencer carries the request-FIFO-drain DEAD_RESPONDER — not the driver's
    drive count, which proactive stimulus would inflate."""
    Generator(_cfg()).generate_all(tmp_path)
    sqr = (tmp_path / "sndr_sequencer.svh").read_text()
    assert "function void check_phase" in sqr
    assert "request_fifo.used() != 0" in sqr
    assert "DEAD_RESPONDER" in sqr


def test_plain_responder_has_no_drain_check(tmp_path):
    """A non-proactive responder keeps the legacy wiring: no sequencer drain check, and it
    is NOT a stimulus target (byte-identical elsewhere)."""
    # a plain on_request responder, DUT-initiated (no test sequence targeting it)
    cfg = ProjectConfig(
        project=ProjectMeta(name="hyb"),
        dut=DutConfig(name="dev"),
        agents=[_hybrid_agent(proactive=False)],
        tests=[TConf(name="t1", num_items=10)],
        analysis=AnalysisConfig(scoreboards=[ScoreboardSpec(name="sb", source="sndr")]),
    )
    Generator(cfg).generate_all(tmp_path)
    sqr = (tmp_path / "sndr_sequencer.svh").read_text()
    assert "request_fifo.used() != 0" not in sqr


# ---- validation -----------------------------------------------------------


def test_proactive_requires_responder():
    with pytest.raises(
        Exception, match="`proactive` is only valid with `mode: responder`"
    ):
        AgentConfig(
            name="a",
            interface="a_if",
            sequence_item="a_item",
            mode="initiator",
            proactive=True,
            ports={"inputs": [PortConfig(name="d", width=8)]},
        )


def test_proactive_requires_on_request():
    with pytest.raises(Exception, match="`proactive` requires `respond: on_request`"):
        _hybrid_agent(respond="prefetch")


def test_proactive_incompatible_with_idle():
    """The continuous (idle) responder drives every cycle — no room for proactive
    stimulus to interleave. Reject the combination rather than silently mis-generate."""
    with pytest.raises(Exception, match="`proactive` is incompatible with `idle`"):
        AgentConfig(
            name="sndr",
            interface="sndr_if",
            sequence_item="sndr_item",
            mode="responder",
            request_valid="ping",
            respond="on_request",
            proactive=True,
            idle={"resp": 0},
            ports={
                "inputs": [PortConfig(name="resp", width=1)],
                "outputs": [PortConfig(name="ping", width=1, randomize=False)],
            },
        )
