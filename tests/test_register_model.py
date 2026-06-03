"""Phase C4a — front-door register-model (RAL) integration.

The reg block is generated externally (reggen); QuickUVM generates the adapter
skeleton (reg2bus/bus2reg as pragmas), the env/test wiring (build+lock model,
map.set_sequencer, optional explicit-prediction predictor), and an optional
hw_reset/bit_bash register test. Omitting `register_model` changes nothing.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    RegisterModelConfig,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _ag(n="spi"):
    return AgentConfig(
        name=n,
        interface=f"{n}_if",
        sequence_item=f"{n}_trans",
        ports={
            "outputs": [PortConfig(name="rsp_data", width=8, randomize=False)],
            "inputs": [PortConfig(name="cmd_addr", width=8)],
        },
    )


def _rm(**over):
    base = dict(
        package="angle_sensor_regs_uvm_pkg",
        block="angle_sensor_regs_c",
        map="default_map",
        bus_agent="spi",
        adapter="spi_reg_adapter",
    )
    base.update(over)
    return RegisterModelConfig(**base)


def _cfg(register_model=None, agents=None, uvm_version="1.2"):
    return ProjectConfig(
        project=ProjectMeta(name="t", uvm_version=uvm_version),
        dut=DutConfig(name="d"),
        agents=agents or [_ag()],
        tests=[TConf(name="t1")],
        register_model=register_model,
    )


# ---- default: no register model => no reg artifacts ------------------------


def test_no_register_model_emits_nothing(tmp_path):
    Generator(_cfg()).generate_all(tmp_path)
    assert not (tmp_path / "spi_reg_adapter.svh").exists()
    assert not (tmp_path / "reg_test.svh").exists()
    assert "reg_model" not in (tmp_path / "env.svh").read_text()
    assert "uvm_reg" not in (tmp_path / "tb_pkg.sv").read_text()


# ---- front-door RAL integration -------------------------------------------


def test_adapter_and_reg_test_generated(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    a = (tmp_path / "spi_reg_adapter.svh").read_text()
    assert "class spi_reg_adapter extends uvm_reg_adapter" in a
    assert "function uvm_sequence_item reg2bus" in a
    assert "function void bus2reg" in a
    # protocol mapping is user code (pragmas)
    assert "pragma quickuvm custom reg2bus begin" in a
    assert "pragma quickuvm custom bus2reg begin" in a
    rt = (tmp_path / "reg_test.svh").read_text()
    assert "uvm_reg_hw_reset_seq" in rt and "uvm_reg_bit_bash_seq" in rt
    assert "env_cfg.reg_model" in rt


def test_model_built_and_locked_in_test_base(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    t = (tmp_path / "test_base.svh").read_text()
    assert 'angle_sensor_regs_c::type_id::create("reg_model")' in t
    assert "env_cfg.reg_model.build();" in t
    assert "env_cfg.reg_model.lock_model();" in t


def test_env_wires_sequencer_and_predictor(tmp_path):
    Generator(_cfg(_rm(use_predictor=True))).generate_all(tmp_path)
    e = (tmp_path / "env.svh").read_text()
    assert "spi_reg_adapter reg_adapter;" in e
    assert "uvm_reg_predictor #(spi_trans) reg_predictor;" in e
    assert "default_map.set_sequencer(spi_agnt.sqr, reg_adapter);" in e
    assert "spi_agnt.ap.connect(reg_predictor.bus_in);" in e
    assert "default_map.set_auto_predict(0);" in e


def test_no_predictor_uses_auto_predict(tmp_path):
    Generator(_cfg(_rm(use_predictor=False))).generate_all(tmp_path)
    e = (tmp_path / "env.svh").read_text()
    assert "reg_predictor" not in e
    assert "default_map.set_auto_predict(1);" in e


def test_reg_test_can_be_disabled(tmp_path):
    Generator(_cfg(_rm(reg_test=False))).generate_all(tmp_path)
    assert not (tmp_path / "reg_test.svh").exists()
    assert "reg_test.svh" not in (tmp_path / "tb_pkg.sv").read_text()
    # adapter still generated
    assert (tmp_path / "spi_reg_adapter.svh").exists()


def test_tb_pkg_imports_reg_package(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    p = (tmp_path / "tb_pkg.sv").read_text()
    assert "import angle_sensor_regs_uvm_pkg::*;" in p
    assert '`include "spi_reg_adapter.svh"' in p


# ---- backdoor (C4b) --------------------------------------------------------


def test_backdoor_root_adds_hdl_path(tmp_path):
    Generator(_cfg(_rm(backdoor_root="top.dut_inst.regs_inst"))).generate_all(tmp_path)
    t = (tmp_path / "test_base.svh").read_text()
    assert 'env_cfg.reg_model.add_hdl_path("top.dut_inst.regs_inst");' in t


def test_no_backdoor_root_no_hdl_path(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    assert "add_hdl_path(" not in (tmp_path / "test_base.svh").read_text()


def test_backdoor_door_sets_default_door_uvm12(tmp_path):
    # default uvm_version == "1.2"
    Generator(_cfg(_rm(backdoor_root="top.r", reg_test_door="backdoor"))).generate_all(
        tmp_path
    )
    rt = (tmp_path / "reg_test.svh").read_text()
    assert "set_default_door(UVM_BACKDOOR);" in rt


def test_backdoor_uvm11d_uses_explicit_mirror(tmp_path):
    Generator(
        _cfg(_rm(backdoor_root="top.r", reg_test_door="backdoor"), uvm_version="1.1d")
    ).generate_all(tmp_path)
    rt = (tmp_path / "reg_test.svh").read_text()
    # 1.1d built-ins hardcode front-door -> explicit per-register backdoor mirror
    assert "mirror(status, UVM_CHECK, UVM_BACKDOOR)" in rt
    assert "set_default_door(UVM_BACKDOOR);" not in rt
    assert "get_registers(regs)" in rt


def test_frontdoor_door_no_backdoor_call(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    rt = (tmp_path / "reg_test.svh").read_text()
    assert "set_default_door(UVM_BACKDOOR);" not in rt
    assert "UVM_CHECK, UVM_BACKDOOR" not in rt


# ---- custom front-door (C4c) -----------------------------------------------


def test_frontdoor_generated_and_wired(tmp_path):
    Generator(_cfg(_rm(frontdoor="spi_reg_frontdoor"))).generate_all(tmp_path)
    fd = tmp_path / "spi_reg_frontdoor.svh"
    assert fd.exists()
    c = fd.read_text()
    assert "extends uvm_reg_frontdoor" in c
    assert "pragma quickuvm custom frontdoor_body begin" in c
    assert "rg.get_address(rw_info.map)" in c
    t = (tmp_path / "test_base.svh").read_text()
    assert 'spi_reg_frontdoor::type_id::create("reg_fd")' in t
    assert "set_frontdoor(reg_fd," in t
    assert '`include "spi_reg_frontdoor.svh"' in (tmp_path / "tb_pkg.sv").read_text()


def test_no_frontdoor_no_file(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    assert not list(tmp_path.glob("*frontdoor*"))
    assert "set_frontdoor" not in (tmp_path / "test_base.svh").read_text()


# ---- validation ------------------------------------------------------------


def test_unknown_bus_agent_rejected():
    with pytest.raises(Exception, match="register_model.bus_agent references unknown"):
        _cfg(_rm(bus_agent="nope"))


def test_backdoor_door_requires_root():
    with pytest.raises(Exception, match="requires backdoor_root"):
        _rm(reg_test_door="backdoor")  # no backdoor_root


def test_reg_test_disables_datapath_scoreboard(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    rt = (tmp_path / "reg_test.svh").read_text()
    assert 'uvm_config_db#(bit)::set(this, "*", "sb_enable", 0);' in rt
    cmp = (tmp_path / "sb_comparator.svh").read_text()
    assert 'uvm_config_db#(bit)::get(this, "", "sb_enable", enabled)' in cmp
    assert "if (!enabled) begin" in cmp
