"""M1 — multi AGENT-DRIVEN resets. Each agent drives its OWN reset input port (the
driver parks it, sequences constrain it inactive, the monitor re-samples it), at its own
polarity. Single-reset benches fall back to the global dut.reset (byte-identical)."""

from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

SIMPLE_REG = (
    Path(__file__).resolve().parents[1] / "examples" / "simple_reg" / "simple_reg.yaml"
)
DUALREG = Path(__file__).resolve().parents[1] / "examples" / "dualreg" / "dualreg.yaml"


def _dual(tmp_path, a_extra="", b_extra="", dut_extra=""):
    p = tmp_path / "m.yaml"
    p.write_text(
        "project: {name: dr}\n"
        f"dut: {{name: dr, clock: clk, reset: a_rst_n, reset_active_low: true{dut_extra}}}\n"
        "clock: {period: 10}\n"
        "agents:\n"
        f"  - {{name: a, interface: a_if, sequence_item: a_it,{a_extra}\n"
        "     ports: {inputs: [{name: a_rst_n, width: 1, randomize: true},"
        " {name: adin, width: 8}], outputs: [{name: adout, width: 8}]}}\n"
        f"  - {{name: b, interface: b_if, sequence_item: b_it,{b_extra}\n"
        "     ports: {inputs: [{name: b_rst, width: 1, randomize: true},"
        " {name: bdin, width: 8}], outputs: [{name: bdout, width: 8}]}}\n"
        "tests: [{name: t}]\n"
    )
    return p


# ---- resolver ---------------------------------------------------------------


def test_single_reset_falls_back_to_dut_reset():
    # simple_reg: the reg agent owns port rst_n and sets no reset_port → falls back to
    # dut.reset with dut.reset_active_low (byte-identical).
    cfg = ProjectConfig.from_yaml(SIMPLE_REG)
    adr = cfg.agent_driven_reset(cfg.agents[0])
    assert (adr.name, adr.active_low) == ("rst_n", True)


def test_external_reset_has_no_agent_driven_reset():
    cfg = ProjectConfig.from_yaml(
        Path(__file__).resolve().parents[1] / "examples" / "reqrsp" / "reqrsp.yaml"
    )
    assert cfg.agent_driven_reset(cfg.agents[0]) is None


def test_per_agent_reset_and_polarity():
    cfg = ProjectConfig.from_yaml(DUALREG)
    a = next(x for x in cfg.agents if x.name == "a")
    b = next(x for x in cfg.agents if x.name == "b")
    assert cfg.agent_driven_reset(a) == ("a_rst_n", True)  # implicit, active-low
    assert cfg.agent_driven_reset(b) == ("b_rst", False)  # explicit, active-high


# ---- generated output: byte-identity pin + mixed polarity -------------------


def test_simple_reg_agent_driven_reset_text_pinned(tmp_path):
    # pin the exact agent-driven reset text so the per-agent refactor can't drift it.
    Generator(ProjectConfig.from_yaml(SIMPLE_REG)).generate_all(tmp_path)
    assert "vif.rst_n <= '0;" in (tmp_path / "reg_driver.svh").read_text()
    assert "tr.rst_n=='1;" in (tmp_path / "reg_seq.svh").read_text()
    mon = (tmp_path / "reg_monitor.svh").read_text()
    assert "if (!vif.rst_n) t.rst_n = '0;" in mon
    cov = (tmp_path / "reg_cov.svh").read_text()
    assert "bins dorst  = {'0};" in cov and "bins norst  = {'1};" in cov


def test_mixed_polarity_multi_agent_reset(tmp_path):
    Generator(ProjectConfig.from_yaml(DUALREG)).generate_all(tmp_path)
    # agent a: active-low — park '0, constrain inactive '1, monitor !vif
    a_drv = (tmp_path / "a_driver.svh").read_text()
    assert "vif.a_rst_n <= '0;" in a_drv
    assert "tr.a_rst_n=='1;" in (tmp_path / "a_seq.svh").read_text()
    assert (
        "if (!vif.a_rst_n) t.a_rst_n = '0;" in (tmp_path / "a_monitor.svh").read_text()
    )
    # agent b: active-high — park '1, constrain inactive '0, monitor vif (no !)
    b_drv = (tmp_path / "b_driver.svh").read_text()
    assert "vif.b_rst <= '1;" in b_drv
    assert "tr.b_rst=='0;" in (tmp_path / "b_seq.svh").read_text()
    assert "if (vif.b_rst) t.b_rst = '1;" in (tmp_path / "b_monitor.svh").read_text()
    # each interface / DUT bound to the right reset (no cross-wire)
    top = (tmp_path / "tb_top.sv").read_text()
    assert ".a_rst_n(a_if_inst.a_rst_n)" in top
    assert ".b_rst(b_if_inst.b_rst)" in top


# ---- validators (fail-closed) -----------------------------------------------


def test_reset_port_not_input_port_rejected(tmp_path):
    p = _dual(tmp_path, b_extra=" reset_port: nope,")
    with pytest.raises(Exception, match="is not one of its input ports"):
        ProjectConfig.from_yaml(p)


def test_reset_port_with_external_reset_rejected(tmp_path):
    # external reset is top-generated (dut.reset is NOT an agent port), so combining it
    # with an agent-driven reset_port is a conflict.
    p = tmp_path / "m.yaml"
    p.write_text(
        "project: {name: dr}\n"
        "dut: {name: dr, clock: clk, reset: sys_rst_n, external_reset: true}\n"
        "clock: {period: 10}\n"
        "agents:\n"
        "  - {name: a, interface: a_if, sequence_item: a_it, reset_port: a_rst_n,\n"
        "     ports: {inputs: [{name: a_rst_n, width: 1, randomize: true},"
        " {name: adin, width: 8}], outputs: [{name: adout, width: 8}]}}\n"
        "  - {name: b, interface: b_if, sequence_item: b_it,\n"
        "     ports: {inputs: [{name: bdin, width: 8}], outputs: [{name: bdout, width: 8}]}}\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="cannot be combined with dut.external_reset"):
        ProjectConfig.from_yaml(p)


def test_reset_port_active_low_without_reset_port_rejected(tmp_path):
    p = _dual(tmp_path, b_extra=" reset_port_active_low: false,")
    with pytest.raises(Exception, match="requires reset_port"):
        ProjectConfig.from_yaml(p)
