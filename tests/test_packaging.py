"""F2 — VIP package restructuring (`layout: flat | packaged`).

`flat` (default) keeps the single <dut>_tb_pkg (byte-identical, verified on the
examples). `packaged` splits it into a standalone <agent>_pkg per agent, a
<dut>_env_pkg, and a <dut>_test_pkg, each with its own .f filelist.
"""

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


def _ag(n):
    return AgentConfig(
        name=n,
        interface=f"{n}_if",
        sequence_item=f"{n}_seq_item",
        ports={
            "outputs": [PortConfig(name=f"{n}_dout", width=8, randomize=False)],
            "inputs": [PortConfig(name=f"{n}_din", width=8)],
        },
    )


def _cfg(layout="flat", agents=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d"),
        agents=agents or [_ag("io")],
        tests=[TConf(name="t1")],
        layout=layout,
    )


# ---- flat (default) keeps the single tb_pkg ---------------------------------


def test_flat_default_emits_tb_pkg(tmp_path):
    Generator(_cfg()).generate_all(tmp_path)
    assert (tmp_path / "d_tb_pkg.sv").exists()
    assert (tmp_path / "pkg.f").exists()
    # no packaged artifacts
    assert not (tmp_path / "io_pkg.sv").exists()
    assert not (tmp_path / "d_env_pkg.sv").exists()
    assert "import d_tb_pkg::*;" in (tmp_path / "tb_top.sv").read_text()
    assert "-f pkg.f" in (tmp_path / "run.f").read_text()


# ---- packaged splits into per-package files ---------------------------------


def test_packaged_emits_per_package_files(tmp_path):
    Generator(_cfg(layout="packaged")).generate_all(tmp_path)
    for f in (
        "io_pkg.sv",
        "io_pkg.f",
        "d_env_pkg.sv",
        "d_env_pkg.f",
        "d_test_pkg.sv",
        "d_test_pkg.f",
    ):
        assert (tmp_path / f).exists(), f
    # the flat package + filelist are gone
    assert not (tmp_path / "d_tb_pkg.sv").exists()
    assert not (tmp_path / "pkg.f").exists()


def test_agent_pkg_is_standalone(tmp_path):
    Generator(_cfg(layout="packaged")).generate_all(tmp_path)
    p = (tmp_path / "io_pkg.sv").read_text()
    assert "package io_pkg;" in p
    assert "import uvm_pkg::*;" in p
    # the agent VIP includes only its own components — no env/scoreboard leakage
    assert '`include "io_seq_item.svh"' in p
    assert '`include "io_driver.svh"' in p
    for leak in ("predictor", "comparator", "scoreboard", "_env", "_test"):
        assert leak not in p, leak
    # white-box import + extra-sequence hooks survive (pragma blocks present)
    assert "pragma quickuvm custom imports" in p
    assert "pragma quickuvm custom sequences_additional" in p
    # its .f compiles the interface BEFORE the package (it references virtual io_if)
    f = (tmp_path / "io_pkg.f").read_text()
    assert "+incdir+." in f
    assert f.index("io_if.sv") < f.index("io_pkg.sv")


def test_env_pkg_imports_agents_and_holds_scoreboard(tmp_path):
    Generator(_cfg(layout="packaged")).generate_all(tmp_path)
    e = (tmp_path / "d_env_pkg.sv").read_text()
    assert "package d_env_pkg;" in e
    assert "import io_pkg::*;" in e
    assert '`include "d_predictor.svh"' in e
    assert '`include "d_env.svh"' in e
    assert '`include "d_reference_model.svh"' in e
    # env .f pulls in the agent VIP .f BEFORE the env package (which imports it)
    f = (tmp_path / "d_env_pkg.f").read_text()
    assert f.index("-f io_pkg.f") < f.index("d_env_pkg.sv")


def test_test_pkg_imports_env_and_holds_tests(tmp_path):
    Generator(_cfg(layout="packaged")).generate_all(tmp_path)
    t = (tmp_path / "d_test_pkg.sv").read_text()
    assert "package d_test_pkg;" in t
    assert "import d_env_pkg::*;" in t
    assert "import io_pkg::*;" in t
    assert '`include "d_base_test.svh"' in t
    assert '`include "t1.svh"' in t
    f = (tmp_path / "d_test_pkg.f").read_text()
    assert f.index("-f d_env_pkg.f") < f.index("d_test_pkg.sv")


def test_packaged_top_and_run_f_target_test_pkg(tmp_path):
    Generator(_cfg(layout="packaged")).generate_all(tmp_path)
    assert "import d_test_pkg::*;" in (tmp_path / "tb_top.sv").read_text()
    assert "-f d_test_pkg.f" in (tmp_path / "run.f").read_text()


def test_multi_agent_packaged_one_pkg_per_agent(tmp_path):
    Generator(_cfg(layout="packaged", agents=[_ag("io"), _ag("aux")])).generate_all(
        tmp_path
    )
    assert (tmp_path / "io_pkg.sv").exists()
    assert (tmp_path / "aux_pkg.sv").exists()
    e = (tmp_path / "d_env_pkg.sv").read_text()
    assert "import io_pkg::*;" in e and "import aux_pkg::*;" in e
    # 2 active agents auto-scaffold a vsqr + vseq → they live in the env package
    assert '`include "d_virtual_sequencer.svh"' in e


def test_packaged_register_model_wires_imports(tmp_path):
    cfg = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d"),
        agents=[_ag("io")],
        tests=[TConf(name="t1")],
        register_model=RegisterModelConfig(
            package="d_ral_pkg",
            block="d_reg_block",
            bus_agent="io",
            adapter="d_adapter",
        ),
        layout="packaged",
    )
    Generator(cfg).generate_all(tmp_path)
    e = (tmp_path / "d_env_pkg.sv").read_text()
    assert "import d_ral_pkg::*;" in e  # env imports the external reg package
    assert '`include "d_adapter.svh"' in e
    t = (tmp_path / "d_test_pkg.sv").read_text()
    assert "import d_ral_pkg::*;" in t  # base_test creates the reg block
    assert '`include "d_reg_test.svh"' in t
    # the env .f has a hook to compile the external reg package before the env
    f = (tmp_path / "d_env_pkg.f").read_text()
    assert "env_pkg_extra_files" in f
