"""Phase F1 — configuration objects + uvm_config_db + working active/passive.

Verifies the config flow: top.sv sets the vif into the config DB, test_base builds
an env_config with per-agent configs (active/passive from YAML) and fetches the vif,
the env distributes each agent config, and the agent consumes it. Also guards the
previously-unwired `active` flag.
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
    TestConfig as TConf,
)

EXAMPLE_CONFIG = Path(__file__).parent.parent / "examples" / "simple_reg" / "simple_reg.yaml"


@pytest.fixture(scope="module")
def tb(tmp_path_factory):
    out = tmp_path_factory.mktemp("cfgtb")
    Generator(ProjectConfig.from_yaml(EXAMPLE_CONFIG)).generate_all(out)
    return out


def _agent(name, active=True):
    return AgentConfig(
        name=name, interface=f"{name}_if", transaction=f"{name}_trans", active=active,
        ports={"outputs": [PortConfig(name="dout", width=8, randomize=False)],
               "inputs": [PortConfig(name="din", width=8)]},
    )


def _cfg(agents):
    return ProjectConfig(project=ProjectMeta(name="t"), dut=DutConfig(name="t_dut"),
                         agents=agents, tests=[TConf(name="test1")])


# ---- config object generation --------------------------------------------

def test_agent_and_env_config_files_generated(tb):
    assert (tb / "reg_config.svh").exists()
    assert (tb / "env_config.svh").exists()


def test_agent_config_holds_vif_and_is_active(tb):
    c = (tb / "reg_config.svh").read_text()
    assert "class reg_config extends uvm_object" in c
    assert "uvm_active_passive_enum is_active" in c
    assert "virtual reg_if vif" in c


def test_env_config_aggregates_agent_config(tb):
    c = (tb / "env_config.svh").read_text()
    assert "class env_config extends uvm_object" in c
    assert "reg_config reg_cfg" in c


# ---- config_db wiring (no more uvm_resource_db) ---------------------------

def test_top_sets_vif_via_config_db(tb):
    t = (tb / "top.sv").read_text()
    assert "uvm_config_db#(virtual reg_if)::set(null, \"*\", \"reg_if_vif\"" in t
    assert "uvm_resource_db" not in t


def test_agent_gets_config_and_no_resource_db(tb):
    a = (tb / "reg_agent.svh").read_text()
    assert "uvm_config_db#(reg_config)::get(this, \"\", \"cfg\", cfg)" in a
    assert "is_active = cfg.is_active;" in a
    assert "vif       = cfg.vif;" in a
    assert "uvm_resource_db" not in a


def test_env_distributes_agent_config(tb):
    e = (tb / "env.svh").read_text()
    assert "uvm_config_db#(env_config)::get(this, \"\", \"env_cfg\", env_cfg)" in e
    assert "uvm_config_db#(reg_config)::set(this, \"reg_agnt\", \"cfg\", env_cfg.reg_cfg)" in e


def test_test_base_builds_and_sets_env_config(tb):
    t = (tb / "test_base.svh").read_text()
    assert "env_cfg = env_config::type_id::create(\"env_cfg\")" in t
    assert "env_cfg.reg_cfg.is_active = UVM_ACTIVE" in t
    assert "uvm_config_db#(env_config)::set(this, \"e\", \"env_cfg\", env_cfg)" in t


# ---- the active/passive flag actually works now ---------------------------

def test_active_flag_drives_is_active(tmp_path):
    Generator(_cfg([_agent("a0", active=False)])).generate_all(tmp_path)
    # config default reflects passive
    assert "is_active = UVM_PASSIVE" in (tmp_path / "a0_config.svh").read_text()
    # test_base sets it passive
    assert "a0_cfg.is_active = UVM_PASSIVE" in (tmp_path / "test_base.svh").read_text()
    # agent still gates driver/sequencer creation on is_active
    a = (tmp_path / "a0_agent.svh").read_text()
    assert "if (is_active == UVM_ACTIVE) begin" in a


def test_active_true_is_active_active(tmp_path):
    Generator(_cfg([_agent("a0", active=True)])).generate_all(tmp_path)
    assert "is_active = UVM_ACTIVE" in (tmp_path / "a0_config.svh").read_text()
    assert "a0_cfg.is_active = UVM_ACTIVE" in (tmp_path / "test_base.svh").read_text()
