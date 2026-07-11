"""K2 — whitebox PROBE observation (`probes:`).

Opt-in taps of INTERNAL DUT signals via a hierarchical reference (XMR) republished on
a generated probe interface (OBSERVE-only) + a passive probe monitor for coverage.
Byte-identical when absent (locked across examples by test_example_byte_identity; the
wbx example exercises the ON path end-to-end on Xcelium, incl. a mutation proof).
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProbeConfig,
    ProjectConfig,
    ProjectMeta,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _ag(n="cmd"):
    return AgentConfig(
        name=n,
        interface=f"{n}_if",
        sequence_item=f"{n}_it",
        ports={
            "inputs": [
                PortConfig(name="push", width=1),
                PortConfig(name="data", width=8),
            ],
            "outputs": [PortConfig(name="busy", width=1, randomize=False)],
        },
    )


def _cfg(probes=None):
    return ProjectConfig(
        project=ProjectMeta(name="d"),
        dut=DutConfig(name="d", reset="rst_n", external_reset=True),
        agents=[_ag()],
        tests=[TConf(name="t")],
        probes=probes or [],
    )


def _gen(tmp_path, probes):
    Generator(_cfg(probes)).generate_all(tmp_path)
    return tmp_path


# ---- byte-identical when absent --------------------------------------------


def test_absent_emits_no_probe_artifacts(tmp_path):
    _gen(tmp_path, [])
    assert not (tmp_path / "d_probe_if.sv").exists()
    assert not (tmp_path / "d_probe_monitor.svh").exists()
    assert "probe_if" not in (tmp_path / "tb_top.sv").read_text()
    assert "probe_mon" not in (tmp_path / "d_env.svh").read_text()


# ---- interface: raw taps + clocking + SVA hook -----------------------------


def test_probe_interface_fields_and_clocking(tmp_path):
    _gen(
        tmp_path,
        [
            ProbeConfig(name="lvl", path="u_fifo.fill", width=3),
            ProbeConfig(name="st", path="u_c.st", enum={"A": 0, "B": 1}, width=2),
            ProbeConfig(name="acc", path="u_dsp.acc", real=True),
        ],
    )
    ifc = (tmp_path / "d_probe_if.sv").read_text()
    # raw bits for integral; real declared directly
    assert "logic [2:0] lvl;" in ifc
    assert "logic [1:0] st;" in ifc
    assert "real acc;" in ifc
    # integral probes are in the sampling clocking block; the real one is NOT
    assert "input lvl;" in ifc and "input st;" in ifc
    assert "input acc;" not in ifc
    assert "pragma quickuvm custom probe_sva begin" in ifc


# ---- top: XMR taps (relative to the DUT instance) + config_db publish -------


def test_top_xmr_and_config_db(tmp_path):
    _gen(tmp_path, [ProbeConfig(name="lvl", path="u_fifo.fill_level", width=3)])
    top = (tmp_path / "tb_top.sv").read_text()
    assert "d_probe_if probe_if (.clk(clk), .rst_n(rst_n));" in top
    assert "assign probe_if.lvl = dut_inst.u_fifo.fill_level;" in top
    assert (
        'uvm_config_db#(virtual d_probe_if)::set(null, "*", "d_probe_vif", probe_if);'
        in top
    )


# ---- monitor: symbolic enum coverage via $cast -----------------------------


def test_probe_monitor_symbolic_coverage(tmp_path):
    _gen(
        tmp_path,
        [
            ProbeConfig(name="lvl", path="u_fifo.fill", width=3, coverage=True),
            ProbeConfig(
                name="st",
                path="u_c.st",
                enum={"A": 0, "B": 1, "C": 2},
                width=2,
                coverage=True,
            ),
        ],
    )
    mon = (tmp_path / "d_probe_monitor.svh").read_text()
    assert "} st_e;" in mon  # black-box enum typedef for symbolic bins
    assert "st_e s_st;" in mon
    assert "void'($cast(s_st, vif.mon_cb.st));" in mon  # cast raw -> typed
    assert "s_lvl = vif.mon_cb.lvl;" in mon  # plain width: direct
    assert "cp_st: coverpoint s_st;" in mon
    # the env instantiates the probe monitor
    assert (
        "probe_mon = d_probe_monitor::type_id::create"
        in (tmp_path / "d_env.svh").read_text()
    )


def test_probes_without_coverage_skip_monitor(tmp_path):
    # observe + SVA only (no coverage) -> interface + taps, but NO probe monitor
    _gen(tmp_path, [ProbeConfig(name="lvl", path="u_fifo.fill", width=3)])
    assert (tmp_path / "d_probe_if.sv").exists()
    assert not (tmp_path / "d_probe_monitor.svh").exists()
    assert "probe_mon" not in (tmp_path / "d_env.svh").read_text()


# ---- fail-closed validation ------------------------------------------------


def test_real_probe_rejects_coverage():
    with pytest.raises(Exception, match="covergroup"):
        ProbeConfig(name="a", path="x", real=True, coverage=True)


def test_real_probe_exclusive_with_width():
    with pytest.raises(Exception, match="exclusive"):
        ProbeConfig(name="a", path="x", real=True, width=4)


def test_probe_empty_path_rejected():
    with pytest.raises(Exception, match="non-empty"):
        ProbeConfig(name="a", path="   ")


def test_probe_name_collides_with_agent_port_rejected():
    with pytest.raises(Exception, match="collides"):
        _cfg([ProbeConfig(name="push", path="u.x")])  # 'push' is an agent port


def test_probe_duplicate_names_rejected():
    with pytest.raises(Exception, match="unique"):
        _cfg([ProbeConfig(name="p", path="a"), ProbeConfig(name="p", path="b")])


def test_probe_unknown_clock_rejected():
    with pytest.raises(Exception, match="not a declared clock"):
        _cfg([ProbeConfig(name="p", path="x", clock="nope")])
