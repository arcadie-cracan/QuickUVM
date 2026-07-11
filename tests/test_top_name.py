"""Phase 3 — opt-in top module name (`top_name`, default 'tb_top').

The default reproduces the historical tb_top module / file / run.f entry / `-top`
/ NOVIF references byte-for-byte (locked across every example by
test_example_byte_identity). Setting `top_name` renames all of them coherently.
An illegal SystemVerilog identifier is rejected up front.
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

_REPO = Path(__file__).resolve().parents[1]


def _ag(n: str = "io") -> AgentConfig:
    return AgentConfig(
        name=n,
        interface=f"{n}_if",
        sequence_item=f"{n}_seq_item",
        ports={
            "inputs": [PortConfig(name=f"{n}_din", width=8)],
            "outputs": [PortConfig(name=f"{n}_dout", width=8, randomize=False)],
        },
    )


def _cfg(top_name: str | None = None) -> ProjectConfig:
    kw = {} if top_name is None else {"top_name": top_name}
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d"),
        agents=[_ag()],
        tests=[TConf(name="t1")],
        **kw,
    )


def test_default_top_name_is_tb_top(tmp_path):
    Generator(_cfg()).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "module tb_top;" in top
    assert "// This File: tb_top.sv" in top
    assert "\ntb_top.sv\n" in (tmp_path / "run.f").read_text()


def test_top_name_renames_module_file_filelist_and_novif(tmp_path):
    Generator(_cfg(top_name="tb")).generate_all(tmp_path)

    # The top module + its file are renamed; the old name is gone.
    assert (tmp_path / "tb.sv").exists()
    assert not (tmp_path / "tb_top.sv").exists()
    top = (tmp_path / "tb.sv").read_text()
    assert "module tb;" in top
    assert "// This File: tb.sv" in top

    # The run.f filelist lists the renamed top and nowhere mentions the old name.
    runf = (tmp_path / "run.f").read_text()
    assert "\ntb.sv\n" in runf
    assert "tb_top" not in runf

    # The NOVIF fatal's hint points at the renamed file.
    base_test = (tmp_path / "d_base_test.svh").read_text()
    assert "see tb.sv)" in base_test
    assert "tb_top" not in base_test


def test_top_name_on_subsystem_renames_top_and_dash_top(tmp_path):
    # The H1 subsystem path renders the top via the same {{ top_name }} — exercise it
    # end-to-end (module, file, and the elaboration `-top`) on the csoc example.
    cfg = ProjectConfig.from_yaml(_REPO / "examples" / "csoc" / "csoc.yaml")
    cfg.top_name = "tb"
    Generator(cfg).generate_all(tmp_path)

    assert (tmp_path / "tb.sv").exists()
    assert not (tmp_path / "tb_top.sv").exists()
    assert "module tb;" in (tmp_path / "tb.sv").read_text()
    runf = (tmp_path / "run.f").read_text()
    assert "-top tb\n" in runf
    assert "tb_top" not in runf


def test_top_name_rejects_illegal_identifier():
    with pytest.raises(Exception, match="top_name"):
        _cfg(top_name="tb top")  # embedded space
    with pytest.raises(Exception, match="top_name"):
        _cfg(top_name="1tb")  # leading digit
    with pytest.raises(Exception, match="reserved"):
        _cfg(top_name="module")  # SystemVerilog keyword
