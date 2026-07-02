"""C3 — multi-instantiation (`instances:` on a parameterized agent).

One parameterized VIP class set is generated once; the env/top instantiate it
per instance at each instance's concrete width, and each instance gets its own
interface, DUT and scoreboard. Opt-in: an agent with no `instances` keeps the
legacy single-instantiation wiring (byte-identical, covered elsewhere).
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
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _inst_ag(name="io"):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        parameters=[ParamConfig(name="W", default=8)],
        instances=[
            InstanceConfig(name="io8", values={"W": 8}),
            InstanceConfig(name="io16", values={"W": 16}),
        ],
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


# ---- one shared VIP class set, N instantiations -----------------------------


def test_instances_share_one_parameterized_vip_class_set(tmp_path):
    Generator(_cfg([_inst_ag()])).generate_all(tmp_path)
    # The VIP classes are generated ONCE, parameterized (not per-instance).
    drv = (tmp_path / "io_driver.svh").read_text()
    assert "class io_driver #(parameter int W = 8)" in drv
    assert not (tmp_path / "io8_driver.svh").exists()
    assert not (tmp_path / "io16_driver.svh").exists()


def test_instances_env_instantiates_per_instance(tmp_path):
    Generator(_cfg([_inst_ag()])).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    assert "io_agent#(8)  io8_agnt;" in e
    assert "io_agent#(16)  io16_agnt;" in e
    assert "d_io8_scoreboard  io8_sb;" in e
    assert "d_io16_scoreboard  io16_sb;" in e
    assert "io8_agnt = io_agent#(8)::type_id::create" in e
    assert "io16_agnt = io_agent#(16)::type_id::create" in e
    assert "io8_agnt.ap.connect(io8_sb.axp);" in e
    assert "io16_agnt.ap.connect(io16_sb.axp);" in e


def test_instances_top_per_instance_interfaces_and_duts(tmp_path):
    Generator(_cfg([_inst_ag()])).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "io_if#(8) io8_if_inst (" in top
    assert "io_if#(16) io16_if_inst (" in top
    # one DUT per instance at its own width
    assert "d#(8) io8_dut (" in top
    assert "d#(16) io16_dut (" in top
    # distinct vif keys disambiguate the two interfaces
    assert 'uvm_config_db#(virtual io_if#(8))::set(null, "*", "io8_vif"' in top
    assert 'uvm_config_db#(virtual io_if#(16))::set(null, "*", "io16_vif"' in top


def test_instances_per_instance_scoreboards_typed_on_width(tmp_path):
    Generator(_cfg([_inst_ag()])).generate_all(tmp_path)
    p8 = (tmp_path / "d_io8_predictor.svh").read_text()
    assert "uvm_subscriber #(io_seq_item#(8))" in p8
    p16 = (tmp_path / "d_io16_predictor.svh").read_text()
    assert "uvm_subscriber #(io_seq_item#(16))" in p16
    r16 = (tmp_path / "d_io16_reference_model.svh").read_text()
    assert "predict(io_seq_item#(16) t)" in r16


def test_instances_cfg_handles_and_vif_get_per_instance(tmp_path):
    Generator(_cfg([_inst_ag()])).generate_all(tmp_path)
    ecfg = (tmp_path / "d_env_cfg.svh").read_text()
    assert "io_cfg#(8) io8_cfg;" in ecfg
    assert "io_cfg#(16) io16_cfg;" in ecfg
    bt = (tmp_path / "d_base_test.svh").read_text()
    assert 'uvm_config_db#(virtual io_if#(8))::get(this, "", "io8_vif"' in bt
    assert 'uvm_config_db#(virtual io_if#(16))::get(this, "", "io16_vif"' in bt


def test_instances_test_forks_a_sequence_per_instance(tmp_path):
    Generator(_cfg([_inst_ag()])).generate_all(tmp_path)
    t = (tmp_path / "t1.svh").read_text()
    assert "io_seq#(8) io8_seq;" in t
    assert "io_seq#(16) io16_seq;" in t
    assert "io8_seq.start(e.io8_agnt.sqr);" in t
    assert "io16_seq.start(e.io16_agnt.sqr);" in t


# ---- validation -------------------------------------------------------------


def test_instances_require_parameters():
    with pytest.raises(Exception, match="requires `parameters`"):
        AgentConfig(
            name="io",
            interface="io_if",
            sequence_item="io_t",
            instances=[InstanceConfig(name="io8")],
            ports={"inputs": [PortConfig(name="din", width=8)]},
        )


def test_duplicate_instance_name_rejected():
    with pytest.raises(Exception, match="duplicate instance"):
        AgentConfig(
            name="io",
            interface="io_if",
            sequence_item="io_t",
            parameters=[ParamConfig(name="W", default=8)],
            instances=[InstanceConfig(name="a"), InstanceConfig(name="a")],
            ports={"inputs": [PortConfig(name="din", width_param="W")]},
        )


def test_instance_unknown_parameter_rejected():
    with pytest.raises(Exception, match="unknown parameter"):
        AgentConfig(
            name="io",
            interface="io_if",
            sequence_item="io_t",
            parameters=[ParamConfig(name="W", default=8)],
            instances=[InstanceConfig(name="a", values={"X": 4})],
            ports={"inputs": [PortConfig(name="din", width_param="W")]},
        )


def test_instances_require_a_sole_agent():
    other = AgentConfig(
        name="io2",
        interface="io2_if",
        sequence_item="io2_t",
        parameters=[ParamConfig(name="W", default=8)],
        ports={"inputs": [PortConfig(name="d2", width_param="W")]},
    )
    with pytest.raises(Exception, match="single-agent bench"):
        _cfg([_inst_ag(), other])


def test_instances_reject_analysis():
    with pytest.raises(Exception, match="instance already gets its own"):
        _cfg([_inst_ag()], analysis=AnalysisConfig())


def test_instances_reject_packaged_layout():
    with pytest.raises(Exception, match="require the default `layout: flat`"):
        _cfg([_inst_ag()], layout="packaged")
