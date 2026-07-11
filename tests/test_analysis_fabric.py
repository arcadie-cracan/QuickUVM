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
    ReferenceModelConfig,
    ScoreboardSpec,
    StructMember,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _ag(n):
    # ports are prefixed by the agent name so distinct agents (a two-stream source +
    # monitor) get DISTINCT DUT ports — the flat tb_top binds every agent port to one
    # DUT port, so port names must be unique across agents.
    return AgentConfig(
        name=n,
        interface=f"{n}_if",
        sequence_item=f"{n}_trans",
        ports={
            "outputs": [PortConfig(name=f"{n}_dout", width=8, randomize=False)],
            "inputs": [PortConfig(name=f"{n}_din", width=8)],
        },
    )


def _cfg(agents, analysis=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d"),
        agents=agents,
        tests=[TConf(name="t1")],
        analysis=analysis,
    )


# ---- default (no analysis) keeps legacy single-stream wiring --------------


def test_default_env_is_legacy_single_stream(tmp_path):
    Generator(_cfg([_ag("reg")])).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    assert "d_scoreboard sbd;" in e
    assert "reg_cov cov;" in e
    assert "reg_agnt.ap.connect(sbd.axp);" in e
    assert "reg_agnt.ap.connect(cov.analysis_export);" in e


# ---- analysis block: per-agent coverage + scoreboard source ----------------


def test_analysis_wires_per_agent_coverage_and_scoreboard(tmp_path):
    cfg = _cfg(
        [_ag("drv"), _ag("mon")],
        AnalysisConfig(
            coverage=["drv", "mon"],
            scoreboards=[ScoreboardSpec(name="sbd", source="drv")],
        ),
    )
    Generator(cfg).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    # per-agent coverage collectors
    assert "drv_cov drv_cov;" in e
    assert "mon_cov mon_cov;" in e
    assert "drv_agnt.ap.connect(drv_cov.analysis_export);" in e
    assert "mon_agnt.ap.connect(mon_cov.analysis_export);" in e
    # scoreboard bound to its source agent
    assert "d_scoreboard sbd;" in e
    assert "drv_agnt.ap.connect(sbd.axp);" in e
    # legacy primary-only comment must be gone in the data-driven path
    assert "Primary agent" not in e


def test_agent_absent_from_analysis_is_not_connected(tmp_path):
    # 'mon' is instantiated but intentionally routed nowhere.
    cfg = _cfg(
        [_ag("drv"), _ag("mon")],
        AnalysisConfig(
            coverage=["drv"], scoreboards=[ScoreboardSpec(name="sbd", source="drv")]
        ),
    )
    Generator(cfg).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    assert "mon_agent  mon_agnt;" in e  # still instantiated
    assert "mon_cov" not in e  # but no coverage
    assert "mon_agnt.ap.connect" not in e  # and no connection


# ---- validation ------------------------------------------------------------


def test_unknown_coverage_agent_rejected():
    with pytest.raises(Exception, match="unknown agent 'nope'"):
        _cfg([_ag("reg")], AnalysisConfig(coverage=["nope"]))


def test_unknown_scoreboard_source_rejected():
    with pytest.raises(Exception, match="unknown source agent 'nope'"):
        _cfg(
            [_ag("reg")],
            AnalysisConfig(scoreboards=[ScoreboardSpec(name="s", source="nope")]),
        )


def test_duplicate_scoreboard_names_rejected():
    with pytest.raises(Exception, match="scoreboards names must be unique"):
        _cfg(
            [_ag("reg")],
            AnalysisConfig(
                scoreboards=[
                    ScoreboardSpec(name="s", source="reg"),
                    ScoreboardSpec(name="s", source="reg"),
                ]
            ),
        )


# ---- A2: two-stream scoreboard (source → predictor → monitor "actual") ------


def _two_stream(
    source="req",
    monitor="rsp",
    match="in_order",
    match_key=None,
    max_latency=None,
    agents=None,
    **over,
):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d"),
        agents=agents if agents is not None else [_ag("req"), _ag("rsp")],
        tests=[TConf(name="t1")],
        analysis=AnalysisConfig(
            scoreboards=[
                ScoreboardSpec(
                    name="sbd",
                    source=source,
                    monitor=monitor,
                    match=match,
                    match_key=match_key,
                    max_latency=max_latency,
                )
            ]
        ),
        **over,
    )


def test_two_stream_predictor_and_comparator_typed(tmp_path):
    Generator(_two_stream()).generate_all(tmp_path)
    p = (tmp_path / "d_predictor.svh").read_text()
    assert "uvm_subscriber #(req_trans)" in p
    assert "uvm_analysis_port #(rsp_trans) results_ap;" in p
    assert "extern function rsp_trans predict(req_trans t);" in p
    c = (tmp_path / "d_comparator.svh").read_text()
    assert "rsp_trans exp_tr, out_tr;" in c  # comparator typed on the OUTPUT stream


def test_two_stream_scoreboard_and_env_wiring(tmp_path):
    Generator(_two_stream()).generate_all(tmp_path)
    sb = (tmp_path / "d_scoreboard.svh").read_text()
    assert "uvm_analysis_export #(req_trans)  src_axp;" in sb
    assert "uvm_analysis_export #(rsp_trans) mon_axp;" in sb
    assert "src_axp.connect(prd.analysis_export);" in sb
    assert "mon_axp.connect(cmp.out_ap);" in sb
    e = (tmp_path / "d_env.svh").read_text()
    assert "req_agnt.ap.connect(sbd.src_axp);" in e
    assert "rsp_agnt.ap.connect(sbd.mon_axp);" in e


def test_two_stream_reference_model_creates_not_copies(tmp_path):
    Generator(_two_stream()).generate_all(tmp_path)
    rm = (tmp_path / "d_reference_model.svh").read_text()
    assert "function rsp_trans d_predictor::predict(req_trans t);" in rm
    assert 'rsp_trans extr = rsp_trans::type_id::create("extr");' in rm
    assert "extr.copy(t)" not in rm  # cross-type — cannot copy the request into a rsp


def test_single_stream_predictor_unchanged(tmp_path):
    # No monitor → predict(pa)→pa, a single axp (byte-identical to legacy).
    Generator(_cfg([_ag("reg")])).generate_all(tmp_path)
    p = (tmp_path / "d_predictor.svh").read_text()
    assert "uvm_subscriber #(reg_trans)" in p
    assert "extern function reg_trans predict(reg_trans t);" in p
    sb = (tmp_path / "d_scoreboard.svh").read_text()
    assert "uvm_analysis_export #(reg_trans) axp;" in sb
    assert "src_axp" not in sb and "mon_axp" not in sb


def test_unknown_monitor_agent_rejected():
    with pytest.raises(Exception, match="unknown monitor agent"):
        _two_stream(monitor="nope")


def test_monitor_equal_source_rejected():
    with pytest.raises(Exception, match="monitor must differ from"):
        _two_stream(monitor="req")  # source is also "req"


def test_multiple_scoreboards_get_per_sb_typed_classes(tmp_path):
    # Multi-transaction-type: >=2 scoreboards each get their OWN typed predictor/
    # comparator/scoreboard/reference_model, prefixed <dut>_<sbname>_.
    cfg = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d"),
        agents=[_ag("req"), _ag("ra"), _ag("rb")],
        tests=[TConf(name="t1")],
        analysis=AnalysisConfig(
            scoreboards=[
                ScoreboardSpec(name="sa", source="req", monitor="ra"),
                ScoreboardSpec(name="sb", source="req", monitor="rb"),
            ]
        ),
    )
    Generator(cfg).generate_all(tmp_path)
    # per-scoreboard typed sets exist; the shared <dut>_* set does NOT
    assert (tmp_path / "d_sa_predictor.svh").exists()
    assert (tmp_path / "d_sb_scoreboard.svh").exists()
    assert (tmp_path / "d_sa_reference_model.svh").exists()
    assert not (tmp_path / "d_predictor.svh").exists()
    # each predictor typed to its own monitor (output) stream
    assert (
        "ra_trans predict(req_trans t)" in (tmp_path / "d_sa_predictor.svh").read_text()
    )
    assert (
        "rb_trans predict(req_trans t)" in (tmp_path / "d_sb_predictor.svh").read_text()
    )
    # env instantiates each with its own class; tb_pkg includes each set
    e = (tmp_path / "d_env.svh").read_text()
    assert "d_sa_scoreboard sa;" in e
    assert "d_sb_scoreboard sb;" in e
    p = (tmp_path / "d_tb_pkg.sv").read_text()
    assert '`include "d_sa_predictor.svh"' in p
    assert '`include "d_sb_reference_model.svh"' in p


def test_single_two_stream_scoreboard_keeps_dut_prefix(tmp_path):
    # exactly one scoreboard → the shared <dut>_* set (byte-identical), no _<sbname>_
    Generator(_two_stream()).generate_all(tmp_path)
    assert (tmp_path / "d_predictor.svh").exists()
    assert not list(tmp_path.glob("d_sbd_*.svh"))


def _multi(*sbs):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d"),
        agents=[_ag("req"), _ag("ra"), _ag("rb")],
        tests=[TConf(name="t1")],
        analysis=AnalysisConfig(scoreboards=list(sbs)),
    )


def test_multi_scoreboards_carry_their_own_match(tmp_path):
    # two scoreboards in one bench, different match strategies → different comparators
    Generator(
        _multi(
            ScoreboardSpec(name="ord", source="req", monitor="ra"),
            ScoreboardSpec(
                name="ooo",
                source="req",
                monitor="rb",
                match="out_of_order",
                match_key="rb_dout",
            ),
        )
    ).generate_all(tmp_path)
    assert "exp_pool" not in (tmp_path / "d_ord_comparator.svh").read_text()
    assert "exp_pool" in (tmp_path / "d_ooo_comparator.svh").read_text()


def test_multi_single_stream_scoreboard_typed_to_its_source(tmp_path):
    # a single-stream scoreboard in a multi bench must type predict() to its OWN
    # source agent, not agents[0] (regression: the else-branch hardcoded pa).
    Generator(
        _multi(
            ScoreboardSpec(name="ss", source="ra"),  # single-stream, source != pa
            ScoreboardSpec(name="ts", source="req", monitor="rb"),
        )
    ).generate_all(tmp_path)
    rm = (tmp_path / "d_ss_reference_model.svh").read_text()
    assert "function ra_trans d_ss_predictor::predict(ra_trans t)" in rm
    assert "req_trans" not in rm  # not typed to the primary agent


def test_scoreboard_illegal_name_rejected():
    with pytest.raises(Exception, match="scoreboard name"):
        ScoreboardSpec(name="sum-sb", source="req")  # appears in a class name


def test_two_stream_rejects_dpi_c_reference_model():
    with pytest.raises(Exception, match="reference_model.language"):
        _two_stream(reference_model=ReferenceModelConfig(language="c"))


# ---- A2: monitor emit_when (publish only qualified transactions) ------------


def _ag_emit(n, emit_when):
    return AgentConfig(
        name=n,
        interface=f"{n}_if",
        sequence_item=f"{n}_trans",
        ports={
            "outputs": [PortConfig(name="dout", width=8, randomize=False)],
            "inputs": [
                PortConfig(name="vld", width=1),
                PortConfig(name="din", width=8),
            ],
        },
        emit_when=emit_when,
    )


def test_emit_when_gates_monitor_publish(tmp_path):
    Generator(_cfg([_ag_emit("reg", "vld")])).generate_all(tmp_path)
    m = (tmp_path / "reg_monitor.svh").read_text()
    assert "if (tr.vld) ap.write(tr);" in m


def test_no_emit_when_publishes_unconditionally(tmp_path):
    Generator(_cfg([_ag("reg")])).generate_all(tmp_path)
    m = (tmp_path / "reg_monitor.svh").read_text()
    assert "      ap.write(tr);" in m
    assert "if (tr." not in m


def test_emit_when_unknown_port_rejected():
    with pytest.raises(Exception, match="emit_when"):
        _ag_emit("reg", "nope")


def test_emit_when_multibit_port_rejected():
    # the gate is `if (tr.x)` — a multi-bit field would be a reduction-OR, not a
    # clean valid test, so a >1-bit qualifier is rejected.
    with pytest.raises(Exception, match="1-bit valid/handshake"):
        _ag_emit("reg", "din")  # din is 8 bits


# ---- A2: out-of-order matching (queue-per-key pool) -------------------------


def test_out_of_order_comparator_pools_by_key(tmp_path):
    Generator(_two_stream(match="out_of_order", match_key="rsp_dout")).generate_all(
        tmp_path
    )
    c = (tmp_path / "d_comparator.svh").read_text()
    assert "rsp_trans exp_pool [longint][$];" in c
    assert "exp_pool[longint'(e.rsp_dout)].push_back(e);" in c  # pool by key
    assert "exp_pool[k].pop_front();" in c  # match pops the key's front
    assert "SB_NOEXP" in c  # actual with no pending expected → error
    assert "fork" in c  # concurrent pool / match processes


def test_in_order_comparator_has_no_pool(tmp_path):
    Generator(_two_stream(match="in_order")).generate_all(tmp_path)
    c = (tmp_path / "d_comparator.svh").read_text()
    assert "exp_pool" not in c
    assert "pending_exp" in c  # the in-order mid-pair guard


def test_out_of_order_requires_two_stream():
    with pytest.raises(Exception, match="requires a two-stream"):
        ScoreboardSpec(name="s", source="reg", match="out_of_order", match_key="x")


def test_out_of_order_requires_match_key():
    with pytest.raises(Exception, match="requires 'match_key'"):
        ScoreboardSpec(name="s", source="a", monitor="b", match="out_of_order")


def test_match_key_without_out_of_order_rejected():
    with pytest.raises(Exception, match="only used with"):
        ScoreboardSpec(
            name="s", source="a", monitor="b", match="in_order", match_key="x"
        )


def test_match_key_must_be_a_monitor_field():
    with pytest.raises(Exception, match="not a port of the monitor"):
        _two_stream(match="out_of_order", match_key="nope")


def test_match_key_too_wide_rejected():
    # the key is cast to a 64-bit longint, so a >64-bit tag would truncate/collide.
    wide = AgentConfig(
        name="rsp",
        interface="rsp_if",
        sequence_item="rsp_trans",
        ports={"outputs": [PortConfig(name="tag", width=128, randomize=False)]},
    )
    with pytest.raises(Exception, match="64-bit longint"):
        _two_stream(
            monitor="rsp",
            match="out_of_order",
            match_key="tag",
            agents=[_ag("req"), wide],
        )


def test_match_key_composite_rejected():
    # longint'(struct) is illegal SV — a tag must be a scalar integral field.
    structed = AgentConfig(
        name="rsp",
        interface="rsp_if",
        sequence_item="rsp_trans",
        ports={
            "outputs": [
                PortConfig(
                    name="tag",
                    struct=[StructMember(name="a", width=4)],
                    randomize=False,
                )
            ]
        },
    )
    with pytest.raises(Exception, match="scalar integral"):
        _two_stream(
            monitor="rsp",
            match="out_of_order",
            match_key="tag",
            agents=[_ag("req"), structed],
        )


# ---- A2: latency window (max_latency) --------------------------------------


def test_max_latency_emits_window_check(tmp_path):
    Generator(
        _two_stream(match="out_of_order", match_key="rsp_dout", max_latency=8)
    ).generate_all(tmp_path)
    c = (tmp_path / "d_comparator.svh").read_text()
    assert "realtime exp_age [longint][$];" in c
    assert "localparam realtime MaxLatency =" in c  # cycles × clock period
    assert "exp_age[longint'(e.rsp_dout)].push_back($realtime);" in c
    assert "SB_LATENCY" in c


def test_no_max_latency_no_window_check(tmp_path):
    Generator(_two_stream(match="out_of_order", match_key="rsp_dout")).generate_all(
        tmp_path
    )
    c = (tmp_path / "d_comparator.svh").read_text()
    assert "exp_age" not in c
    assert "MaxLatency" not in c
    assert "SB_LATENCY" not in c


def test_max_latency_requires_out_of_order():
    with pytest.raises(Exception, match="max_latency is only supported with"):
        ScoreboardSpec(name="s", source="a", monitor="b", max_latency=5)


def test_max_latency_must_be_positive():
    with pytest.raises(Exception, match="max_latency must be >= 1"):
        ScoreboardSpec(
            name="s",
            source="a",
            monitor="b",
            match="out_of_order",
            match_key="x",
            max_latency=0,
        )
