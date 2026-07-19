"""H2 — BOUNDARY agents: a subsystem top's own top-level agents.

The chip-level UVM shape: block envs inside (`subenvs:`), chip-boundary agents
outside (`agents:` on the same config). The agent becomes a first-class endpoint:

* `connections:` may wire it in either direction — `from: <agent>.<port>` uses a
  port the agent DRIVES (its `inputs`, the house convention), `to: <agent>.<port>`
  a port it SAMPLES (its `outputs`);
* composition scoreboards (`analysis.scoreboards`) may use the BARE agent name;
* the top vseq drives active boundary agents alongside the composed blocks;
* a boundary stimulus agent no cross-block scoreboard touches raises the
  UNCHECKED_AGENT warning (checking scales with stimulus).

Proved on examples/chip (host -> add -> inv -> host.resp, e2e scoreboard):
Xcelium-green; wrong e2e model -> only e2e fails; corrupt add -> add sb + e2e
fail while inv's stays green; drop the e2e -> UNCHECKED_AGENT fires live.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_LEAF = """project: {{name: {n}}}
dut: {{name: {n}, clock: clk, reset: '', combinational: true}}
clock: {{period: 10, unit: ns}}
agents:
  - name: {a}
    interface: {a}_if
    sequence_item: {a}_item
    active: false
    ports:
      inputs:  [{{name: din,  width: 8}}]
      outputs: [{{name: dout, width: 8}}]
tests: [{{name: {n}_t}}]
"""


def _top_yaml(tmp_path, extra="", host_ports=None, sb="", conns=None):
    (tmp_path / "a.yaml").write_text(_LEAF.format(n="blka", a="pa"))
    (tmp_path / "b.yaml").write_text(_LEAF.format(n="blkb", a="pb"))
    ports = host_ports or (
        "      inputs:  [{name: hin,  width: 8}]\n"
        "      outputs: [{name: resp, width: 8}]\n"
    )
    conns = (
        conns
        if conns is not None
        else (
            "connections:\n"
            "  - {from: host.hin, to: blka.din}\n"
            "  - {from: blkb.dout, to: host.resp}\n"
        )
    )
    p = tmp_path / "top.yaml"
    p.write_text(
        "project: {name: soc}\n"
        "layout: packaged\n"
        "dut: {name: soc, clock: clk, reset: '', combinational: true}\n"
        "clock: {period: 10, unit: ns}\n"
        "agents:\n"
        "  - name: host\n"
        "    interface: host_if\n"
        "    sequence_item: host_item\n"
        "    ports:\n" + ports + "subenvs:\n"
        "  - {name: blka, config: a.yaml}\n"
        "  - {name: blkb, config: b.yaml}\n"
        + conns
        + sb
        + "tests: [{name: t}]\n"
        + extra
    )
    return p


def test_boundary_agent_composes_and_generates(tmp_path):
    cfg = ProjectConfig.from_yaml(_top_yaml(tmp_path))
    Generator(cfg).generate_all(tmp_path / "gen", backup=False)
    top = (tmp_path / "gen" / "tb_top.sv").read_text()
    # the boundary interface is instantiated flat-style and wired by the connections
    assert "host_if host_if_inst (clk);" in top
    assert "assign blka_pa_if_inst.din = host_if_inst.hin;" in top
    assert "assign host_if_inst.resp = blkb_pb_if_inst.dout;" in top
    assert '"host_if_vif", host_if_inst' in top
    env = (tmp_path / "gen" / "soc_env.svh").read_text()
    assert "host_agent host_agnt;" in env
    assert "vsqr.host_sqr = host_agnt.sqr;" in env
    # driven-but-unchecked (no scoreboard references host) -> the warning renders
    assert "UNCHECKED_AGENT" in env
    vseq = (tmp_path / "gen" / "soc_vseq.svh").read_text()
    assert "host_seq_h.start(p_sequencer.host_sqr);" in vseq
    bt = (tmp_path / "gen" / "soc_base_test.svh").read_text()
    assert "host_if_vif" in bt
    pkg = (tmp_path / "gen" / "soc_test_pkg.sv").read_text()
    assert "import host_pkg::*;" in pkg
    f = (tmp_path / "gen" / "soc_test_pkg.f").read_text()
    assert "-f host_pkg.f" in f
    # the boundary agent's package was generated at the top level
    assert (tmp_path / "gen" / "host_pkg.sv").exists()


def test_bare_scoreboard_endpoint_silences_the_warning(tmp_path):
    sb = (
        "analysis:\n  scoreboards:\n    - {name: e2e, source: host, monitor: blkb.pb}\n"
    )
    cfg = ProjectConfig.from_yaml(_top_yaml(tmp_path, sb=sb))
    Generator(cfg).generate_all(tmp_path / "gen", backup=False)
    env = (tmp_path / "gen" / "soc_env.svh").read_text()
    assert "host_agnt.ap.connect(e2e.src_axp);" in env
    assert "UNCHECKED_AGENT" not in env


def test_connection_from_must_be_agent_driven_port(tmp_path):
    conns = "connections:\n  - {from: host.resp, to: blka.din}\n"
    with pytest.raises(Exception, match="not a DRIVEN port of boundary agent"):
        ProjectConfig.from_yaml(_top_yaml(tmp_path, conns=conns))


def test_connection_to_must_be_agent_sampled_port(tmp_path):
    conns = (
        "connections:\n"
        "  - {from: host.hin, to: blka.din}\n"
        "  - {from: blkb.dout, to: host.hin}\n"
    )
    with pytest.raises(Exception, match="not a SAMPLED port of boundary agent"):
        ProjectConfig.from_yaml(_top_yaml(tmp_path, conns=conns))


def test_bare_scoreboard_endpoint_must_name_a_boundary_agent(tmp_path):
    sb = "analysis:\n  scoreboards:\n    - {name: e2e, source: ghost, monitor: blkb.pb}\n"
    with pytest.raises(Exception, match="no boundary agent of that name"):
        ProjectConfig.from_yaml(_top_yaml(tmp_path, sb=sb))


def test_boundary_agent_name_collision_with_leaf_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text(_LEAF.format(n="blka", a="host"))
    (tmp_path / "b.yaml").write_text(_LEAF.format(n="blkb", a="pb"))
    p = tmp_path / "top.yaml"
    p.write_text(
        "project: {name: soc}\n"
        "layout: packaged\n"
        "dut: {name: soc, clock: clk, reset: '', combinational: true}\n"
        "clock: {period: 10, unit: ns}\n"
        "agents:\n"
        "  - name: host\n"
        "    interface: host_if\n"
        "    sequence_item: host_item\n"
        "    ports: {inputs: [{name: hin, width: 8}]}\n"
        "subenvs:\n"
        "  - {name: blka, config: a.yaml}\n"
        "  - {name: blkb, config: b.yaml}\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="collides"):
        ProjectConfig.from_yaml(p)


def test_nested_subsystem_may_not_declare_boundary_agents(tmp_path):
    (tmp_path / "a.yaml").write_text(_LEAF.format(n="blka", a="pa"))
    (tmp_path / "b.yaml").write_text(_LEAF.format(n="blkb", a="pb"))
    # a mid-level cluster that declares BOTH subenvs and agents
    (tmp_path / "mid.yaml").write_text(
        "project: {name: mid}\n"
        "layout: packaged\n"
        "dut: {name: mid, clock: clk, reset: '', combinational: true}\n"
        "clock: {period: 10, unit: ns}\n"
        "agents:\n"
        "  - name: mh\n"
        "    interface: mh_if\n"
        "    sequence_item: mh_item\n"
        "    ports: {inputs: [{name: min, width: 8}]}\n"
        "subenvs:\n"
        "  - {name: blka, config: a.yaml}\n"
        "  - {name: blkb, config: b.yaml}\n"
        "tests: [{name: mt}]\n"
    )
    (tmp_path / "c.yaml").write_text(_LEAF.format(n="blkc", a="pc"))
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: soc}\n"
        "layout: packaged\n"
        "dut: {name: soc, clock: clk, reset: '', combinational: true}\n"
        "clock: {period: 10, unit: ns}\n"
        "subenvs:\n"
        "  - {name: mid, config: mid.yaml}\n"
        "  - {name: blkc, config: c.yaml}\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="NESTED subsystem may not declare"):
        ProjectConfig.from_yaml(top)
