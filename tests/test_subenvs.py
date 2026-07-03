"""H1 — sub-environments (`subenvs:` composing >=2 child block envs).

A subsystem (top) bench references each child block's own config; the child's
reusable env layer is generated alongside a top layer (env / env_cfg / virtual
sequencer / vseq / test / tb_top / test_pkg) that composes them. Opt-in: a bench
with no `subenvs` is an ordinary bench (byte-identical).
"""

from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
)
from quick_uvm.models import (
    TestConfig as TConf,
)

SOC = Path(__file__).resolve().parents[1] / "examples" / "soc" / "soc.yaml"


def _block(name, agent, iface):
    return ProjectConfig(
        project=ProjectMeta(name=name),
        dut=DutConfig(name=name, combinational=True, reset=""),
        agents=[
            AgentConfig(
                name=agent,
                interface=iface,
                sequence_item=f"{agent}_seq_item",
                ports={"inputs": [PortConfig(name="din", width=8)]},
            )
        ],
        tests=[TConf(name=f"{name}_test")],
    )


def _top(layout="packaged", **extra):
    from quick_uvm.models import SubenvConfig

    return ProjectConfig(
        project=ProjectMeta(name="soc"),
        dut=DutConfig(name="soc", combinational=True, reset=""),
        agents=[],
        layout=layout,
        subenvs=[
            SubenvConfig(name="adder", config="adder/adder.yaml"),
            SubenvConfig(name="inverter", config="inverter/inverter.yaml"),
        ],
        tests=[TConf(name="soc_test")],
        **extra,
    )


# ---- loader (external config files, resolved relative to the top) -----------


def test_from_yaml_resolves_child_configs():
    top = ProjectConfig.from_yaml(SOC)
    assert [s.name for s in top.subenvs] == ["adder", "inverter"]
    assert set(top.subenv_configs) == {"adder", "inverter"}
    assert top.subenv_configs["adder"].dut.name == "adder"
    assert top.subenv_configs["inverter"].agents[0].interface == "b_if"
    views = top.subenv_views
    assert [v.block for v in views] == ["adder", "inverter"]
    assert views[0].env_pkg == "adder_env_pkg"


# ---- generation: child env layers + top composition -------------------------


def _gen(tmp_path):
    Generator(ProjectConfig.from_yaml(SOC)).generate_all(tmp_path)
    return tmp_path


def test_children_emit_env_layer_only(tmp_path):
    _gen(tmp_path)
    # each child's reusable env package + agent VIP
    for f in (
        "adder_env_pkg.sv",
        "a_pkg.sv",
        "a_if.sv",
        "adder_env.svh",
        "adder_scoreboard.svh",
        "inverter_env_pkg.sv",
        "b_pkg.sv",
    ):
        assert (tmp_path / f).exists(), f
    # but NOT a child test / tb_top / clkgen / DUT stub / test_pkg
    for f in (
        "adder_base_test.svh",
        "adder_test.svh",
        "adder.sv",
        "adder_test_pkg.sv",
        "inverter.sv",
    ):
        assert not (tmp_path / f).exists(), f


def test_top_env_composes_children(tmp_path):
    _gen(tmp_path)
    e = (tmp_path / "soc_env.svh").read_text()
    assert "adder_env adder;" in e  # handle != class name (no collision)
    assert "inverter_env inverter;" in e
    assert 'adder = adder_env::type_id::create("adder", this);' in e
    assert "vsqr.adder_a_sqr = adder.a_agnt.sqr;" in e
    assert "vsqr.inverter_b_sqr = inverter.b_agnt.sqr;" in e


def test_top_virtual_sequencer_collects_block_sequencers(tmp_path):
    _gen(tmp_path)
    v = (tmp_path / "soc_virtual_sequencer.svh").read_text()
    assert "a_sequencer adder_a_sqr;" in v
    assert "b_sequencer inverter_b_sqr;" in v


def test_top_vseq_forks_each_block(tmp_path):
    _gen(tmp_path)
    vs = (tmp_path / "soc_vseq.svh").read_text()
    assert "adder_a_seq.start(p_sequencer.adder_a_sqr);" in vs
    assert "inverter_b_seq.start(p_sequencer.inverter_b_sqr);" in vs
    assert "fork" in vs and "join" in vs


def test_top_base_test_populates_child_cfgs(tmp_path):
    _gen(tmp_path)
    bt = (tmp_path / "soc_base_test.svh").read_text()
    assert "env_cfg.adder_cfg = adder_env_cfg::type_id::create" in bt
    assert 'uvm_config_db#(adder_env_cfg)::set(this, "e.adder", "env_cfg"' in bt
    assert '"adder_a_if_vif"' in bt


def test_top_tb_top_instantiates_block_duts(tmp_path):
    _gen(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "a_if adder_a_if_inst (clk);" in top
    assert "b_if inverter_b_if_inst (clk);" in top
    assert "adder adder_dut (" in top
    assert "inverter inverter_dut (" in top
    assert '"adder_a_if_vif", adder_a_if_inst' in top


def test_top_test_pkg_imports_child_env_pkgs(tmp_path):
    _gen(tmp_path)
    pkg = (tmp_path / "soc_test_pkg.sv").read_text()
    assert "import adder_env_pkg::*;" in pkg
    assert "import inverter_env_pkg::*;" in pkg
    assert "import a_pkg::*;" in pkg


# ---- validation -------------------------------------------------------------


def test_subenvs_require_packaged_layout():
    with pytest.raises(Exception, match="layout: packaged"):
        _top(layout="flat")


def test_subenvs_reject_own_agents():
    with pytest.raises(Exception, match="must not define its own `agents`"):
        ProjectConfig(
            project=ProjectMeta(name="soc"),
            dut=DutConfig(name="soc", combinational=True, reset=""),
            layout="packaged",
            agents=[
                AgentConfig(
                    name="x",
                    interface="xi",
                    sequence_item="xt",
                    ports={"inputs": [PortConfig(name="din", width=8)]},
                )
            ],
            subenvs=[
                __import__("quick_uvm.models", fromlist=["SubenvConfig"]).SubenvConfig(
                    name="a", config="a.yaml"
                ),
                __import__("quick_uvm.models", fromlist=["SubenvConfig"]).SubenvConfig(
                    name="b", config="b.yaml"
                ),
            ],
            tests=[TConf(name="t")],
        )


def test_subenvs_require_at_least_two():
    from quick_uvm.models import SubenvConfig

    with pytest.raises(Exception, match=">=2 child block envs"):
        ProjectConfig(
            project=ProjectMeta(name="soc"),
            dut=DutConfig(name="soc", combinational=True, reset=""),
            layout="packaged",
            subenvs=[SubenvConfig(name="only", config="only.yaml")],
            tests=[TConf(name="t")],
        )


def test_cross_child_name_collision_rejected():
    top = _top()
    # two blocks that both use agent name "a" / interface "same_if"
    top.subenv_configs = {
        "adder": _block("adder", "a", "same_if"),
        "inverter": _block("inverter", "a", "same_if"),
    }
    with pytest.raises(Exception, match="collides with another block"):
        top.validate_subenv_composition()


def test_child_dut_name_collision_rejected():
    top = _top()
    top.subenv_configs = {
        "adder": _block("dupblk", "a", "a_if"),
        "inverter": _block("dupblk", "b", "b_if"),
    }
    with pytest.raises(Exception, match="collides with another block or the top"):
        top.validate_subenv_composition()


def test_clocked_child_block_rejected():
    top = _top()
    clocked = ProjectConfig(
        project=ProjectMeta(name="clkblk"),
        dut=DutConfig(name="clkblk", combinational=False, reset="rst_n"),
        agents=[
            AgentConfig(
                name="c",
                interface="c_if",
                sequence_item="c_seq_item",
                ports={"inputs": [PortConfig(name="din", width=8)]},
            )
        ],
        tests=[TConf(name="c_test")],
    )
    top.subenv_configs = {"adder": _block("adder", "a", "a_if"), "inverter": clocked}
    with pytest.raises(Exception, match="only combinational child blocks"):
        top.validate_subenv_composition()


def test_parameterized_child_agent_rejected():
    from quick_uvm.models import ParamConfig

    top = _top()
    param_block = ProjectConfig(
        project=ProjectMeta(name="pblk"),
        dut=DutConfig(name="pblk", combinational=True, reset=""),
        agents=[
            AgentConfig(
                name="p",
                interface="p_if",
                sequence_item="p_seq_item",
                parameters=[ParamConfig(name="W", default=8)],
                ports={"inputs": [PortConfig(name="din", width_param="W")]},
            )
        ],
        tests=[TConf(name="p_test")],
    )
    top.subenv_configs = {
        "adder": _block("adder", "a", "a_if"),
        "inverter": param_block,
    }
    with pytest.raises(Exception, match="parameterized agent is"):
        top.validate_subenv_composition()


def test_top_with_analysis_rejected():
    from quick_uvm.models import AnalysisConfig

    with pytest.raises(Exception, match="must not set analysis"):
        _top(analysis=AnalysisConfig())


def test_generate_without_loaded_children_errors():
    # A top constructed in-memory (not via from_yaml) has no loaded children.
    with pytest.raises(Exception, match="child configs are not loaded"):
        Generator(_top()).files_to_generate()
