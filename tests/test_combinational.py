"""Combinational-DUT support: opt-in dut.combinational.

The TB clock becomes a pure cadence (not connected to the DUT); the DUT stub is
always_comb; and the monitor samples inputs AND outputs together (0-cycle
latency) race-free through a dedicated monitor clocking block. Byte-identical
when off.
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


def _ag(name="bs"):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        transaction=f"{name}_seq_item",
        ports={
            "inputs": [
                PortConfig(name="data_in", width=8),
                PortConfig(name="amt", width=3),
            ],
            "outputs": [PortConfig(name="data_out", width=8)],
        },
    )


def _cfg(*, combinational=False, agents=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=combinational),
        agents=agents or [_ag()],
        tests=[TConf(name="t1")],
    )


# ---- combinational = True --------------------------------------------------


def test_dut_connection_has_no_clock(tmp_path):
    Generator(_cfg(combinational=True)).generate_all(tmp_path)
    top = (tmp_path / "top.sv").read_text()
    # DUT connected to ports only — no .clk / no reset
    assert ".data_out(bs_if_inst.data_out)" in top
    assert ".clk(" not in top
    # interface still gets the cadence clock
    assert "bs_if bs_if_inst (clk);" in top


def test_interface_has_monitor_clocking_block(tmp_path):
    Generator(_cfg(combinational=True)).generate_all(tmp_path)
    iface = (tmp_path / "bs_if.sv").read_text()
    assert "clocking mon_cb @(posedge clk);" in iface
    assert "default input #1step;" in iface
    for sig in ("data_in", "amt", "data_out"):
        assert f"input {sig};" in iface


def test_monitor_samples_via_mon_cb(tmp_path):
    Generator(_cfg(combinational=True)).generate_all(tmp_path)
    mon = (tmp_path / "bs_monitor.svh").read_text()
    assert "@vif.mon_cb;" in mon
    assert "t.data_in = vif.mon_cb.data_in;" in mon
    assert "t.data_out = vif.mon_cb.data_out;" in mon
    assert "@vif.cb1;" not in mon  # no registered-latency wait


def test_dut_stub_is_combinational(tmp_path):
    Generator(_cfg(combinational=True)).generate_all(tmp_path)
    dut = (tmp_path / "d.sv").read_text()
    assert "always_comb" in dut
    assert "always_ff" not in dut
    assert "posedge" not in dut  # no clock/reset ports or sensitivity


# ---- combinational = False is a no-op --------------------------------------


def test_default_is_registered(tmp_path):
    Generator(_cfg(combinational=False)).generate_all(tmp_path)
    top = (tmp_path / "top.sv").read_text()
    iface = (tmp_path / "bs_if.sv").read_text()
    mon = (tmp_path / "bs_monitor.svh").read_text()
    assert ".clk(clk)" in top
    assert "mon_cb" not in iface
    assert "@vif.cb1;" in mon


# ---- validation ------------------------------------------------------------


def test_combinational_and_external_reset_mutually_exclusive():
    with pytest.raises(Exception, match="mutually exclusive"):
        ProjectConfig(
            project=ProjectMeta(name="t"),
            dut=DutConfig(
                name="d", reset="rst_n", external_reset=True, combinational=True
            ),
            agents=[_ag()],
            tests=[TConf(name="t1")],
        )
