"""DUT-interface hardening (pre-existing bug fixes):

- Bug 2: a FLAT bench binds every agent's ports to ONE DUT instance, so two agents
  sharing a port name would double-bind that DUT port (illegal SV) — now rejected.
- Bug 1: the generated <dut>.sv STUB now covers ALL agents' ports (not just the
  first) and never lists an agent-driven reset port twice.
"""

from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig


def _bench(tmp_path, agents_yaml, dut="clk, reset: rst_n, external_reset: true"):
    p = tmp_path / "m.yaml"
    p.write_text(
        "project: {name: b}\n"
        f"dut: {{name: b, clock: {dut}}}\n"
        "clock: {period: 10}\n"
        "agents:\n" + agents_yaml + "tests: [{name: t}]\n"
    )
    return p


_A = (
    "  - {{name: {n}, interface: {n}_if, sequence_item: {n}_it,\n"
    "     ports: {{inputs: [{{name: {p}in, width: 8}}],"
    " outputs: [{{name: {p}out, width: 8}}]}}}}\n"
)


# ---- Bug 2: shared-port-name double-bind guard ------------------------------


def test_two_agents_sharing_a_port_name_rejected(tmp_path):
    # both agents own the same-named ports → the flat tb_top would double-bind them.
    agents = _A.format(n="a", p="d") + _A.format(n="b", p="d")
    with pytest.raises(Exception, match="both have a port"):
        ProjectConfig.from_yaml(_bench(tmp_path, agents))


def test_two_agents_distinct_port_names_ok(tmp_path):
    agents = _A.format(n="a", p="a") + _A.format(n="b", p="b")
    ProjectConfig.from_yaml(_bench(tmp_path, agents))  # must not raise


def test_subenv_leaves_sharing_port_names_ok(tmp_path):
    # each subenv LEAF gets its own DUT instance, so identical leaf port names are fine.
    for blk in ("p", "q"):
        (tmp_path / f"{blk}.yaml").write_text(
            f"project: {{name: {blk}}}\n"
            f"dut: {{name: {blk}, combinational: true, reset: ''}}\n"
            f"agents:\n  - {{name: {blk}a, interface: {blk}_if,"
            f" sequence_item: {blk}_it,\n"
            "     ports: {inputs: [{name: din, width: 8}],"
            " outputs: [{name: dout, width: 8}]}}\n"
            f"tests: [{{name: {blk}_t}}]\n"
        )
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: sub}\n"
        "layout: packaged\n"
        "dut: {name: sub, combinational: true, reset: ''}\n"
        "subenvs:\n  - {name: p, config: p.yaml}\n  - {name: q, config: q.yaml}\n"
        "tests: [{name: sub_t}]\n"
    )
    ProjectConfig.from_yaml(top)  # per-leaf DUTs → no double-bind, must not raise


# ---- Bug 1: DUT stub completeness + no duplicate reset ----------------------


def test_multi_agent_stub_covers_all_agents(tmp_path):
    agents = _A.format(n="a", p="a") + _A.format(n="b", p="b")
    Generator(ProjectConfig.from_yaml(_bench(tmp_path, agents))).generate_all(tmp_path)
    stub = (tmp_path / "b.sv").read_text()
    # ALL agents' ports appear (not just the first agent's)
    for port in ("ain", "aout", "bin", "bout"):
        assert port in stub, port


def test_agent_driven_reset_not_listed_twice_in_stub(tmp_path):
    # simple_reg's reset (rst_n) is an agent input port; the stub must not also emit a
    # separate `input rst_n` (that duplicate port is illegal SV).
    sr = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "simple_reg"
        / "simple_reg.yaml"
    )
    Generator(ProjectConfig.from_yaml(sr)).generate_all(tmp_path)
    stub = (tmp_path / "simple_reg.sv").read_text()
    assert stub.count("input  rst_n,") + stub.count("input               rst_n") == 1


def test_single_agent_external_reset_stub_has_reset_port(tmp_path):
    # when dut.reset is NOT an agent port (external reset), the stub still emits it.
    agents = _A.format(n="a", p="a")
    Generator(ProjectConfig.from_yaml(_bench(tmp_path, agents))).generate_all(tmp_path)
    stub = (tmp_path / "b.sv").read_text()
    assert "input               rst_n" in stub


def test_non_primary_parameterized_agent_rejected(tmp_path):
    # the stub/tb_top thread only the primary agent's params, so a NON-primary
    # parameterized agent (its width_param port would reference an undeclared param) is
    # rejected rather than emitting invalid SV.
    p = tmp_path / "m.yaml"
    p.write_text(
        "project: {name: b}\n"
        "dut: {name: b, clock: clk, reset: rst_n, external_reset: true}\n"
        "clock: {period: 10}\n"
        "auto_virtual_sequences: false\n"
        "agents:\n"
        "  - {name: a, interface: a_if, sequence_item: a_it,\n"
        "     ports: {inputs: [{name: adin, width: 8}], outputs: [{name: adout, width: 8}]}}\n"
        "  - {name: b, interface: b_if, sequence_item: b_it,\n"
        "     parameters: [{name: BW, default: 16}],\n"
        "     ports: {inputs: [{name: bdin, width_param: BW}],"
        " outputs: [{name: bdout, width_param: BW}]}}\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="only the FIRST agent"):
        ProjectConfig.from_yaml(p)
