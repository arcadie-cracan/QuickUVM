"""K1 — interface protocol-checker scaffolding (opt-in `assertions`).

When an agent sets `assertions: true`, its interface gains a sample SVA property
(an output is never X/Z once reset deasserts, gated at the agent's OWN reset
polarity) plus a `sva_properties` pragma region for user SVA. Byte-identical when
off (locked across the examples by test_example_byte_identity; the dualreg example
exercises the mixed-polarity ON path end-to-end on Xcelium).
"""

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


def _iface(tmp_path, dut, agent):
    cfg = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=dut,
        agents=[agent],
        tests=[TConf(name="t1")],
    )
    Generator(cfg).generate_all(tmp_path)
    return (tmp_path / f"{agent.interface}.sv").read_text()


def _agent(assertions=False, **kw):
    return AgentConfig(
        name="io",
        interface="io_if",
        sequence_item="io_seq_item",
        assertions=assertions,
        ports={
            "inputs": [PortConfig(name="d", width=8)],
            "outputs": [PortConfig(name="q", width=8, randomize=False)],
        },
        **kw,
    )


def test_off_by_default_emits_no_checker(tmp_path):
    iface = _iface(
        tmp_path, DutConfig(name="d", reset="rst_n", external_reset=True), _agent()
    )
    assert "interface protocol checker" not in iface
    assert "sva_properties" not in iface
    assert "assert property" not in iface


def test_external_active_low_reset_polarity(tmp_path):
    iface = _iface(
        tmp_path,
        DutConfig(name="d", reset="rst_n", external_reset=True),
        _agent(assertions=True),
    )
    assert "a_q_known: assert property (" in iface
    assert "disable iff (!rst_n) !$isunknown(q))" in iface  # active-low -> '!'
    assert "pragma quickuvm custom sva_properties begin" in iface


def test_agent_driven_active_high_reset_polarity(tmp_path):
    ag = AgentConfig(
        name="io",
        interface="io_if",
        sequence_item="io_seq_item",
        assertions=True,
        reset_port="rst",
        reset_port_active_low=False,
        ports={
            "inputs": [PortConfig(name="rst", width=1), PortConfig(name="d", width=8)],
            "outputs": [PortConfig(name="q", width=8, randomize=False)],
        },
    )
    iface = _iface(tmp_path, DutConfig(name="d", reset="rst"), ag)
    assert "disable iff (rst) !$isunknown(q))" in iface  # active-high -> no '!'
    assert "disable iff (!" not in iface


def test_combinational_no_reset_scaffold_only(tmp_path):
    # no reset -> a live $isunknown would fire at t=0, so only the pragma scaffold ships
    iface = _iface(
        tmp_path,
        DutConfig(name="d", combinational=True, reset=""),
        _agent(assertions=True),
    )
    assert "a_q_known:" not in iface  # no LIVE sample assertion
    assert "!$isunknown" not in iface  # ...and no generated property body
    # the commented example inside the region is expected, and the region ships:
    assert "pragma quickuvm custom sva_properties begin" in iface
    assert "pragma quickuvm custom sva_properties end" in iface
