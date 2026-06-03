"""External-reset support (X0): opt-in dut.external_reset.

When set, QuickUVM declares the reset as an interface port, generates a
reset_generator in top, wires it to each interface, and reset-gates the driver
and monitor. When unset (default), output is byte-identical to before.
"""

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


def _ag(name="bus"):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        transaction=f"{name}_seq_item",
        ports={
            "inputs": [PortConfig(name="addr", width=8)],
            "outputs": [PortConfig(name="data", width=8)],
        },
    )


def _cfg(*, external_reset=False, reset="rst_n_i", agents=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset=reset, external_reset=external_reset),
        agents=agents or [_ag()],
        tests=[TConf(name="t1")],
    )


# ---- external_reset = True emits the full machinery ------------------------


def test_interface_declares_reset_port(tmp_path):
    Generator(_cfg(external_reset=True)).generate_all(tmp_path)
    iface = (tmp_path / "bus_if.sv").read_text()
    assert "interface bus_if (input clk, input rst_n_i);" in iface


def test_top_has_reset_wire_generator_and_named_instantiation(tmp_path):
    Generator(_cfg(external_reset=True)).generate_all(tmp_path)
    top = (tmp_path / "top.sv").read_text()
    assert "logic rst_n_i;" in top
    assert "pragma quickuvm custom reset_generator begin" in top
    assert "rst_n_i = 1'b0;" in top  # assert (active-low)
    assert "rst_n_i = 1'b1;" in top  # deassert
    # >1 interface port -> named connection (Verible module-instantiation rule)
    assert "bus_if bus_if_inst (.clk(clk), .rst_n_i(rst_n_i));" in top


def test_driver_and_monitor_reset_gate(tmp_path):
    Generator(_cfg(external_reset=True)).generate_all(tmp_path)
    drv = (tmp_path / "bus_driver.svh").read_text()
    mon = (tmp_path / "bus_monitor.svh").read_text()
    assert "wait (vif.rst_n_i === 1'b1);" in drv
    assert "wait (vif.rst_n_i === 1'b1);" in mon


def test_active_high_reset_polarity(tmp_path):
    cfg = _cfg(external_reset=True)
    cfg.dut.reset_active_low = False
    Generator(cfg).generate_all(tmp_path)
    top = (tmp_path / "top.sv").read_text()
    drv = (tmp_path / "bus_driver.svh").read_text()
    # discriminating: active-high asserts to 1, deasserts to 0 (the inverse of low)
    assert "rst_n_i = 1'b1;   // assert" in top
    assert "rst_n_i = 1'b0;   // assert" not in top
    assert "wait (vif.rst_n_i === 1'b0);" in drv  # deasserted == 0


# ---- external_reset = False is a no-op ------------------------------------


def test_default_emits_no_external_reset_code(tmp_path):
    Generator(_cfg(external_reset=False)).generate_all(tmp_path)
    top = (tmp_path / "top.sv").read_text()
    iface = (tmp_path / "bus_if.sv").read_text()
    drv = (tmp_path / "bus_driver.svh").read_text()
    assert "reset_generator" not in top
    assert "interface bus_if (input clk);" in iface
    assert "bus_if bus_if_inst (clk);" in top
    assert "wait (vif." not in drv


# ---- validation ------------------------------------------------------------


def test_external_reset_requires_reset_name():
    with pytest.raises(Exception, match="external_reset requires dut.reset"):
        _cfg(external_reset=True, reset="")


def test_external_reset_rejects_agent_driven_reset():
    # reset that is also an agent input port -> ambiguous / would double-drive
    ag = AgentConfig(
        name="bus",
        interface="bus_if",
        transaction="bus_seq_item",
        ports={"inputs": [PortConfig(name="rst_n_i", width=1)], "outputs": []},
    )
    with pytest.raises(Exception, match="agent port"):
        _cfg(external_reset=True, reset="rst_n_i", agents=[ag])


def test_external_reset_rejects_output_port_collision():
    ag = AgentConfig(
        name="bus",
        interface="bus_if",
        transaction="bus_seq_item",
        ports={"inputs": [], "outputs": [PortConfig(name="data", width=8)]},
    )
    with pytest.raises(Exception, match="agent port"):
        _cfg(external_reset=True, reset="data", agents=[ag])


def test_external_reset_rejects_clock_name_collision():
    with pytest.raises(Exception, match="must differ from dut.clock"):
        _cfg(external_reset=True, reset="clk")  # dut.clock defaults to "clk"


# ---- multi-agent fan-out + duplicate-connection fix ------------------------


def test_multi_agent_external_reset_fans_out(tmp_path):
    Generator(_cfg(external_reset=True, agents=[_ag("bus"), _ag("mem")])).generate_all(
        tmp_path
    )
    assert "input rst_n_i" in (tmp_path / "bus_if.sv").read_text()
    assert "input rst_n_i" in (tmp_path / "mem_if.sv").read_text()
    top = (tmp_path / "top.sv").read_text()
    assert "bus_if bus_if_inst (.clk(clk), .rst_n_i(rst_n_i));" in top
    assert "mem_if mem_if_inst (.clk(clk), .rst_n_i(rst_n_i));" in top
    # second agent's monitor/driver also gate
    assert "wait (vif.rst_n_i === 1'b1);" in (tmp_path / "mem_driver.svh").read_text()


def test_reset_connected_once_when_agent_port(tmp_path):
    """Regression: reset as an agent input port must connect to the DUT once, not
    twice (the port loop already emits it)."""
    ag = AgentConfig(
        name="bus",
        interface="bus_if",
        transaction="bus_seq_item",
        ports={
            "inputs": [PortConfig(name="rst_n", width=1)],
            "outputs": [PortConfig(name="data", width=8)],
        },
    )
    cfg = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="rst_n", external_reset=False),
        agents=[ag],
        tests=[TConf(name="t1")],
    )
    Generator(cfg).generate_all(tmp_path)
    top = (tmp_path / "top.sv").read_text()
    assert top.count(".rst_n(bus_if_inst.rst_n)") == 1


def test_external_reset_regen_is_idempotent(tmp_path):
    """Regenerating the same external_reset config preserves the reset_generator
    region and does not error (fail-closed merge round-trips the default body)."""
    cfg = _cfg(external_reset=True)
    Generator(cfg).generate_all(tmp_path)
    first = (tmp_path / "top.sv").read_text()
    Generator(cfg).generate_all(tmp_path)  # regenerate over the existing tree
    assert (tmp_path / "top.sv").read_text() == first
    assert "pragma quickuvm custom reset_generator begin" in first
