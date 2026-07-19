"""C3 — parameterized agent VIP (`parameters:` + `width_param:`).

An agent with `parameters` makes its interface AND all UVM classes `#(...)`-
parameterized, so the same VIP is reusable at different widths; the env/top
instantiate it at concrete default values. Opt-in: no `parameters` is
byte-identical (verified on the examples).
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    AnalysisConfig,
    CoverageModel,
    Coverpoint,
    DutConfig,
    ParamConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    ReferenceModelConfig,
    RegisterModelConfig,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _ag(name="io"):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        ports={
            "inputs": [PortConfig(name="din", width=8)],
            "outputs": [PortConfig(name="dout", width=8, randomize=False)],
        },
    )


def _param_ag(name="io", w=8):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        parameters=[ParamConfig(name="W", default=w)],
        ports={
            "inputs": [PortConfig(name="din", width_param="W")],
            "outputs": [PortConfig(name="dout", width_param="W", randomize=False)],
        },
    )


def _cfg(agents, **extra):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", combinational=True, reset=""),
        agents=agents,
        tests=[TConf(name="t1")],
        **extra,
    )


# ---- a plain agent is NOT parameterized (byte-identical baseline) ------------


def test_plain_agent_not_parameterized(tmp_path):
    Generator(_cfg([_ag()])).generate_all(tmp_path)
    assert "interface io_if (" in (tmp_path / "io_if.sv").read_text()
    txn = (tmp_path / "io_seq_item.svh").read_text()
    assert "class io_seq_item extends" in txn
    assert "`uvm_object_utils(io_seq_item)" in txn  # not param_utils


# ---- a parameterized agent threads #(W) everywhere --------------------------


def test_param_interface_and_port_widths(tmp_path):
    Generator(_cfg([_param_ag()])).generate_all(tmp_path)
    ifc = (tmp_path / "io_if.sv").read_text()
    assert "interface io_if #(parameter int W = 8) (" in ifc
    assert "logic [W-1:0] din;" in ifc
    assert "logic [W-1:0] dout;" in ifc


def test_param_uvm_classes(tmp_path):
    Generator(_cfg([_param_ag()])).generate_all(tmp_path)
    txn = (tmp_path / "io_seq_item.svh").read_text()
    assert "class io_seq_item #(parameter int W = 8) extends uvm_sequence_item;" in txn
    assert "`uvm_object_param_utils(io_seq_item#(W))" in txn
    assert "rand bit [W-1:0] din;" in txn
    drv = (tmp_path / "io_driver.svh").read_text()
    assert (
        "class io_driver #(parameter int W = 8) extends uvm_driver #(io_seq_item#(W));"
        in drv
    )
    assert "virtual io_if#(W) vif;" in drv
    assert "`uvm_component_param_utils(io_driver#(W))" in drv


def test_param_env_and_top_instantiate_at_concrete_width(tmp_path):
    Generator(_cfg([_param_ag()])).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    assert "io_agent#(8)  io_agnt;" in e
    assert "io_agnt = io_agent#(8)::type_id::create" in e
    assert "uvm_config_db#(io_cfg#(8))::set" in e
    top = (tmp_path / "tb_top.sv").read_text()
    assert "io_if#(8) io_if_inst (" in top
    assert "uvm_config_db#(virtual io_if#(8))::set" in top
    ecfg = (tmp_path / "d_env_cfg.svh").read_text()
    assert "io_cfg#(8) io_cfg;" in ecfg


def test_param_scoreboard_typed_on_param_transaction(tmp_path):
    Generator(_cfg([_param_ag()])).generate_all(tmp_path)
    p = (tmp_path / "d_predictor.svh").read_text()
    assert "uvm_subscriber #(io_seq_item#(8))" in p
    assert "predict(io_seq_item#(8) t)" in p


def test_param_default_test_creates_param_sequence(tmp_path):
    Generator(_cfg([_param_ag()])).generate_all(tmp_path)
    t = (tmp_path / "t1.svh").read_text()
    assert "io_seq#(8) seq;" in t
    assert "io_seq#(8)::type_id::create" in t


# ---- validation -------------------------------------------------------------


def test_width_param_must_reference_a_declared_parameter():
    with pytest.raises(Exception, match="not a declared parameter"):
        AgentConfig(
            name="io",
            interface="io_if",
            sequence_item="io_t",
            ports={"inputs": [PortConfig(name="din", width_param="X")]},
        )


def test_width_param_scalar_only():
    with pytest.raises(Exception, match="only for a scalar"):
        PortConfig(name="din", width_param="W", enum={"A": 0})


def test_width_param_or_width_not_both():
    with pytest.raises(Exception, match="width_param OR width"):
        PortConfig(name="din", width_param="W", width=8)


def test_duplicate_parameter_rejected():
    with pytest.raises(Exception, match="duplicate parameter"):
        AgentConfig(
            name="io",
            interface="io_if",
            sequence_item="io_t",
            parameters=[
                ParamConfig(name="W", default=8),
                ParamConfig(name="W", default=4),
            ],
            ports={"inputs": [PortConfig(name="din", width_param="W")]},
        )


# ---- project-level fail-closed guards (combos not yet parameter-threaded) ----


def test_param_agent_rejects_dpi_c_reference_model():
    from quick_uvm.models import AnalysisConfig, ScoreboardSpec

    with pytest.raises(Exception, match="DPI-C marshaling"):
        _cfg(
            [_param_ag()],
            analysis=AnalysisConfig(
                scoreboards=[
                    ScoreboardSpec(
                        name="sbd",
                        source=_param_ag().name,
                        reference_model=ReferenceModelConfig(language="c"),
                    )
                ]
            ),
        )


def test_param_agent_rejects_coverage_model():
    with pytest.raises(Exception, match="covergroups need concrete"):
        _cfg(
            [_param_ag()],
            coverage_models=[
                CoverageModel(agent="io", coverpoints=[Coverpoint(field="din")])
            ],
        )


def test_param_agent_rejects_analysis_coverage():
    with pytest.raises(Exception, match="analysis.coverage"):
        _cfg([_param_ag()], analysis=AnalysisConfig(coverage=["io"]))


def test_param_agent_rejects_register_model():
    with pytest.raises(Exception, match="RAL adapter/predictor"):
        _cfg(
            [_param_ag()],
            register_model=RegisterModelConfig(
                package="p_pkg", block="p_blk", bus_agent="io"
            ),
        )


def test_param_agent_rejects_virtual_sequences():
    # Two agents ⇒ an auto virtual sequence is generated; the vseq classes are
    # not parameterized, so this must fail closed.
    a = AgentConfig(
        name="a",
        interface="a_if",
        sequence_item="a_seq_item",
        parameters=[ParamConfig(name="W", default=8)],
        ports={"inputs": [PortConfig(name="a_in", width_param="W")]},
    )
    b = AgentConfig(
        name="b",
        interface="b_if",
        sequence_item="b_seq_item",
        parameters=[ParamConfig(name="W", default=8)],
        ports={"inputs": [PortConfig(name="b_in", width_param="W")]},
    )
    with pytest.raises(Exception, match="virtual sequences are not supported"):
        _cfg([a, b])
