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
    assert not (tmp_path / "d_reg_test.svh").exists()
    assert "reg_model" not in (tmp_path / "d_env.svh").read_text()
    assert "uvm_reg" not in (tmp_path / "d_tb_pkg.sv").read_text()


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
    rt = (tmp_path / "d_reg_test.svh").read_text()
    assert "uvm_reg_hw_reset_seq" in rt and "uvm_reg_bit_bash_seq" in rt
    assert "env_cfg.reg_model" in rt


def test_model_built_and_locked_in_test_base(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    t = (tmp_path / "d_base_test.svh").read_text()
    assert 'angle_sensor_regs_c::type_id::create("reg_model")' in t
    assert "env_cfg.reg_model.build();" in t
    assert "env_cfg.reg_model.lock_model();" in t


def test_env_wires_sequencer_and_predictor(tmp_path):
    Generator(_cfg(_rm(use_predictor=True))).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    # Handle is named distinctly from the class so a user adapter named
    # "reg_adapter" can't shadow its own type (uvm_reg_adapter create).
    assert "spi_reg_adapter bus_adapter;" in e
    assert "uvm_reg_predictor #(spi_trans) reg_predictor;" in e
    assert "default_map.set_sequencer(spi_agnt.sqr, bus_adapter);" in e
    assert "spi_agnt.ap.connect(reg_predictor.bus_in);" in e
    assert "default_map.set_auto_predict(0);" in e


def test_no_predictor_uses_auto_predict(tmp_path):
    Generator(_cfg(_rm(use_predictor=False))).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    assert "reg_predictor" not in e
    assert "default_map.set_auto_predict(1);" in e


def test_reg_test_can_be_disabled(tmp_path):
    Generator(_cfg(_rm(reg_test=False))).generate_all(tmp_path)
    assert not (tmp_path / "d_reg_test.svh").exists()
    assert "d_reg_test.svh" not in (tmp_path / "d_tb_pkg.sv").read_text()
    # adapter still generated
    assert (tmp_path / "spi_reg_adapter.svh").exists()


def test_tb_pkg_imports_reg_package(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    p = (tmp_path / "d_tb_pkg.sv").read_text()
    assert "import angle_sensor_regs_uvm_pkg::*;" in p
    assert '`include "spi_reg_adapter.svh"' in p


# ---- backdoor (C4b) --------------------------------------------------------


def test_backdoor_root_adds_hdl_path(tmp_path):
    Generator(_cfg(_rm(backdoor_root="top.dut_inst.regs_inst"))).generate_all(tmp_path)
    t = (tmp_path / "d_base_test.svh").read_text()
    assert 'env_cfg.reg_model.add_hdl_path("top.dut_inst.regs_inst");' in t


def test_no_backdoor_root_no_hdl_path(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    assert "add_hdl_path(" not in (tmp_path / "d_base_test.svh").read_text()


def test_backdoor_door_sets_default_door_uvm12(tmp_path):
    # default uvm_version == "1.2"
    Generator(_cfg(_rm(backdoor_root="top.r", reg_test_door="backdoor"))).generate_all(
        tmp_path
    )
    rt = (tmp_path / "d_reg_test.svh").read_text()
    assert "set_default_door(UVM_BACKDOOR);" in rt


def test_backdoor_uvm11d_uses_explicit_mirror(tmp_path):
    Generator(
        _cfg(_rm(backdoor_root="top.r", reg_test_door="backdoor"), uvm_version="1.1d")
    ).generate_all(tmp_path)
    rt = (tmp_path / "d_reg_test.svh").read_text()
    # 1.1d built-ins hardcode front-door -> explicit per-register backdoor mirror
    assert "mirror(status, UVM_CHECK, UVM_BACKDOOR)" in rt
    assert "set_default_door(UVM_BACKDOOR);" not in rt
    assert "get_registers(regs)" in rt


def test_frontdoor_door_no_backdoor_call(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    rt = (tmp_path / "d_reg_test.svh").read_text()
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
    t = (tmp_path / "d_base_test.svh").read_text()
    assert 'spi_reg_frontdoor::type_id::create("reg_fd")' in t
    assert "set_frontdoor(reg_fd," in t
    assert '`include "spi_reg_frontdoor.svh"' in (tmp_path / "d_tb_pkg.sv").read_text()


def test_no_frontdoor_no_file(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    assert not list(tmp_path.glob("*frontdoor*"))
    assert "set_frontdoor" not in (tmp_path / "d_base_test.svh").read_text()


# ---- validation ------------------------------------------------------------


def test_unknown_bus_agent_rejected():
    with pytest.raises(Exception, match="register_model.bus_agent references unknown"):
        _cfg(_rm(bus_agent="nope"))


def test_backdoor_door_requires_root():
    with pytest.raises(Exception, match="requires backdoor_root"):
        _rm(reg_test_door="backdoor")  # no backdoor_root


def test_reg_test_disables_datapath_scoreboard(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    rt = (tmp_path / "d_reg_test.svh").read_text()
    assert 'uvm_config_db#(bit)::set(this, "*", "sb_enable", 0);' in rt
    cmp = (tmp_path / "d_comparator.svh").read_text()
    assert 'uvm_config_db#(bit)::get(this, "", "sb_enable", enabled)' in cmp
    assert "if (!enabled) begin" in cmp


def test_disabled_scoreboard_reports_info_not_novec(tmp_path):
    # A deliberately-disabled scoreboard comparing 0 transactions must NOT warn
    # (NOVEC); that warning is reserved for an *enabled* scoreboard that saw none.
    Generator(_cfg(_rm())).generate_all(tmp_path)
    cmp = (tmp_path / "d_comparator.svh").read_text()
    assert "else if (!enabled)" in cmp
    novec = cmp.index("NOVEC")
    assert "else if (VECT_CNT == 0)" in cmp[:novec]  # NOVEC guarded by enabled+0


# ---- handle/class collision regression -------------------------------------


def test_adapter_handle_distinct_from_class(tmp_path):
    # A user adapter literally named "reg_adapter" must not have the env handle
    # shadow its own type (handle::type_id::create would fail to bind).
    Generator(_cfg(_rm(adapter="reg_adapter"))).generate_all(tmp_path)
    e = (tmp_path / "d_env.svh").read_text()
    assert "reg_adapter bus_adapter;" in e
    assert 'bus_adapter = reg_adapter::type_id::create("bus_adapter");' in e
    assert "reg_adapter reg_adapter;" not in e


# ---- C5 — RAL-driven CSR test library --------------------------------------


def test_csr_test_specs_maps_kinds_to_builtin_seqs():
    rm = _rm(csr_tests=["hw_reset", "bit_bash", "rw", "mem_walk", "shared"])
    specs = rm.csr_test_specs
    assert [s["kind"] for s in specs] == [
        "hw_reset",
        "bit_bash",
        "rw",
        "mem_walk",
        "shared",
    ]
    assert [s["seq"] for s in specs] == [
        "uvm_reg_hw_reset_seq",
        "uvm_reg_bit_bash_seq",
        "uvm_reg_access_seq",
        "uvm_mem_walk_seq",
        "uvm_reg_shared_access_seq",
    ]


def test_no_csr_tests_emits_none(tmp_path):
    Generator(_cfg(_rm())).generate_all(tmp_path)
    assert not list(tmp_path.glob("*_csr_*_test.svh"))
    # byte-identical guarantee: no csr trace leaks into the package include list.
    assert "csr" not in (tmp_path / "d_tb_pkg.sv").read_text()


def test_csr_tests_coexist_with_reg_test(tmp_path):
    # csr_tests adds tests alongside reg_test; it does not replace it.
    Generator(_cfg(_rm(reg_test=True, csr_tests=["hw_reset"]))).generate_all(tmp_path)
    assert (tmp_path / "d_reg_test.svh").exists()
    assert (tmp_path / "d_csr_hw_reset_test.svh").exists()
    p = (tmp_path / "d_tb_pkg.sv").read_text()
    assert '`include "d_reg_test.svh"' in p
    assert '`include "d_csr_hw_reset_test.svh"' in p


def test_csr_tests_generate_per_kind_files(tmp_path):
    Generator(_cfg(_rm(csr_tests=["hw_reset", "rw"]))).generate_all(tmp_path)
    assert (tmp_path / "d_csr_hw_reset_test.svh").exists()
    assert (tmp_path / "d_csr_rw_test.svh").exists()
    assert not (tmp_path / "d_csr_bit_bash_test.svh").exists()


def test_csr_test_runs_correct_builtin_seq(tmp_path):
    Generator(_cfg(_rm(csr_tests=["bit_bash"]))).generate_all(tmp_path)
    t = (tmp_path / "d_csr_bit_bash_test.svh").read_text()
    assert "class d_csr_bit_bash_test extends d_base_test" in t
    assert "uvm_reg_bit_bash_seq seq;" in t
    assert "seq.model = env_cfg.reg_model;" in t
    assert "seq.start(null);" in t
    # RAL is the checker => data-path scoreboard disabled
    assert 'uvm_config_db#(bit)::set(this, "*", "sb_enable", 0);' in t


def test_csr_tests_included_in_tb_pkg(tmp_path):
    Generator(_cfg(_rm(csr_tests=["hw_reset", "rw"]))).generate_all(tmp_path)
    p = (tmp_path / "d_tb_pkg.sv").read_text()
    assert '`include "d_csr_hw_reset_test.svh"' in p
    assert '`include "d_csr_rw_test.svh"' in p


def test_duplicate_csr_tests_rejected():
    with pytest.raises(Exception, match="csr_tests has duplicate kinds"):
        _rm(csr_tests=["rw", "hw_reset", "rw"])


def test_unknown_csr_test_kind_rejected():
    with pytest.raises(Exception, match="csr_tests"):
        _rm(csr_tests=["nope"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("adapter", "bus_adapter"),
        ("block", "reg_model"),
        ("frontdoor", "reg_fd"),
        ("adapter", "reg_predictor"),
    ],
)
def test_class_name_colliding_with_env_handle_rejected(field, value):
    # A user class name equal to a generated env handle would shadow its own type.
    with pytest.raises(Exception, match="collides with a generated env handle"):
        _rm(**{field: value})
