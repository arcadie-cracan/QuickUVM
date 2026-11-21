"""The DUT's reset port must be driven by SOMEBODY: inference, wall, static gate.

The defect: a single-reset bench wires `dut.reset` one of two ways — the top
generates it (`reset: {external: true}`) or an agent drives it (the port is one of
that agent's ports). A config with NEITHER validated, `generate` exited 0, and
tb_top carried::

    .rst_n(cmd_if_inst.rst_n)        // cmd_if has no `rst_n`

Xcelium rejects it at ELABORATION (``*E,CUVUNF: Hierarchical name component lookup
failed for 'rst_n'``). It shipped unnoticed because nothing in the committed corpus
is in that shape (every example is no-reset, external, a reset list, or
agent-driven) — but `dut.reset` DEFAULTS to `rst_n` and `external` to false, so a
config that says nothing about the reset is in it: 130 of this suite's own tests
built one, and so did every bench QuickUVM Architect wrote for a DUT with a reset.

Three layers:

* INFERENCE — with no agent declaring the port there is one way left to drive it, so
  an unset `external` resolves to the top-driven reset (`_infer_reset_driver`), and
  `resolved()` reports it as `inferred`;
* a WALL — an explicit `external: false` (or a `reset_port` under another name) with
  no agent declaring the port is refused with a teaching error (`undriven_reset`);
* a STATIC GATE — `svcheck.find_dangling_dut_connections` checks the GENERATED top
  of every example: the check that stands in for a simulator, and catches the same
  class of defect whatever its cause.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig
from quick_uvm.svcheck import find_dangling_dut_connections

_REPO = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO / "examples"


def _cfg(**over):
    base = {
        "project": {"name": "t", "author": "x"},
        "dut": {"name": "d", "clock": "clk", "reset": "rst_n"},
        "agents": [
            {
                "name": "cmd",
                "interface": "cmd_if",
                "sequence_item": "cmd_item",
                "ports": {
                    "inputs": [{"name": "din", "width": 8}],
                    "outputs": [{"name": "dout", "width": 8}],
                },
            }
        ],
        "tests": [{"name": "rand_test"}],
    }
    base.update(over)
    return base


def _with_port(cfg, side, name="rst_n", agent=0):
    cfg["agents"][agent]["ports"].setdefault(side, []).append({"name": name})
    return cfg


def _gate(out: Path) -> list[str]:
    sources = {p.name: p.read_text() for p in out.rglob("*.sv")}
    violations: list[str] = []
    for name, text in sources.items():
        if "pragma quickuvm custom dut_connections begin" in text:
            violations.extend(find_dangling_dut_connections(text, sources, name))
    return violations


# --- 1. inference: nobody drives it => the top does ----------------------------


def test_an_undriven_reset_is_driven_by_the_top(tmp_path):
    """The shape that shipped broken now generates the top-driven reset."""
    cfg = ProjectConfig.model_validate(_cfg())
    assert cfg.dut.external_reset is True
    assert cfg.reset_driver_inferred is True
    Generator(cfg).generate_all(tmp_path, backup=False)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "logic rst_n;" in top
    assert "pragma quickuvm custom reset_generator begin" in top
    assert "cmd_if cmd_if_inst (.clk(clk), .rst_n(rst_n));" in top
    assert (
        "interface cmd_if (input clk, input rst_n);"
        in (tmp_path / "cmd_if.sv").read_text()
    )
    assert _gate(tmp_path) == []


def test_the_default_reset_name_is_inferred_too():
    """`dut.reset` defaults to `rst_n`: saying nothing about the reset is the shape."""
    cfg = _cfg()
    del cfg["dut"]["reset"]
    assert ProjectConfig.model_validate(cfg).dut.external_reset is True


def test_inference_honours_the_polarity(tmp_path):
    cfg = ProjectConfig.model_validate(_cfg(reset={"active_low": False}))
    assert cfg.reset_driver_inferred is True
    Generator(cfg).generate_all(tmp_path, backup=False)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "rst_n = 1'b1;   // assert" in top
    assert "rst_n = 1'b0;   // deassert" in top


def test_resolved_reports_who_drives_the_reset():
    """The one default that changes the generated INTERFACES must be reviewable."""
    inferred = ProjectConfig.model_validate(_cfg()).resolved()["reset"]
    assert inferred == {"name": "rst_n", "driver": "top", "origin": "inferred"}
    declared = ProjectConfig.model_validate(_cfg(reset={"external": True}))
    assert declared.resolved()["reset"] == {
        "name": "rst_n",
        "driver": "top",
        "origin": "declared",
    }
    by_agent = ProjectConfig.model_validate(_with_port(_cfg(), "inputs"))
    assert by_agent.resolved()["reset"] == {
        "name": "rst_n",
        "driver": "agent:cmd",
        "origin": "declared",
    }
    none = _cfg()
    none["dut"]["reset"] = ""
    assert ProjectConfig.model_validate(none).resolved()["reset"] is None


def test_the_inferred_flag_cannot_be_written_in_yaml():
    with pytest.raises(ValidationError, match="set internally"):
        ProjectConfig.model_validate(_cfg(reset_driver_inferred=True))


@pytest.mark.parametrize("side", ["inputs", "outputs", "inouts"])
def test_an_agent_declared_reset_is_left_alone(side):
    """Any agent, any side: the interface then HAS the signal tb_top connects, and
    `external: true` next to it would be refused — nothing is inferred."""
    two = _cfg()
    two["agents"].append(
        {
            "name": "rsp",
            "interface": "rsp_if",
            "sequence_item": "rsp_item",
            "ports": {"inputs": [{"name": "ready"}]},
        }
    )
    cfg = ProjectConfig.model_validate(_with_port(two, side, agent=1))
    assert cfg.dut.external_reset is False
    assert cfg.reset_driver_inferred is False


def test_nothing_is_inferred_where_no_reset_is_wired():
    no_reset = _cfg()
    no_reset["dut"]["reset"] = ""
    comb = _cfg()
    comb["dut"]["combinational"] = True
    domains = _cfg(reset=[{"name": "rst_n"}])
    for raw in (no_reset, comb, domains):
        cfg = ProjectConfig.model_validate(raw)
        assert cfg.dut.external_reset is False
        assert cfg.reset_driver_inferred is False


def test_a_vip_and_its_selftest_agree_by_default(tmp_path):
    """The same rule on every `kind`: a VIP whose interfaces take the reset is
    self-tested by a top that GENERATES it. (`kind: selftest` + a top-driven reset
    used to instantiate the interface with the clock only — `rst_n` an unconnected
    input the drivers waited on forever, exit 0.)"""
    for kind in ("vip", "selftest"):
        raw = _cfg(kind=kind, layout="packaged")
        if kind == "vip":
            del raw["tests"]
        cfg = ProjectConfig.model_validate(raw)
        assert cfg.dut.external_reset is True, kind
        out = tmp_path / kind
        Generator(cfg).generate_all(out, backup=False)
        iface = next(out.rglob("cmd_if.sv")).read_text()
        assert "interface cmd_if (input clk, input rst_n);" in iface
        if kind == "selftest":
            top = next(out.rglob("tb_top.sv")).read_text()
            assert "logic rst_n;" in top
            assert "pragma quickuvm custom reset_generator begin" in top
            assert "cmd_if cmd_if_inst (.clk(clk), .rst_n(rst_n));" in top


# --- 2. the wall: the config SAID an agent drives it, and none does -----------


def test_explicit_external_false_with_no_agent_port_is_refused():
    with pytest.raises(ValidationError, match="driven by nobody") as e:
        ProjectConfig.model_validate(_cfg(reset={"external": False}))
    msg = str(e.value)
    # the error teaches all three ways out
    assert "drop `external: false`" in msg
    assert "ports.inputs" in msg
    assert "dut.reset: ''" in msg


def test_explicit_external_false_with_an_agent_port_is_fine():
    cfg = _with_port(_cfg(reset={"external": False}), "inputs")
    assert ProjectConfig.model_validate(cfg).dut.external_reset is False


def test_reset_port_with_a_mismatched_dut_reset_names_the_fix():
    """`reset_port: arst` + the default `dut.reset: rst_n`: tb_top connected
    `.arst(...)` AND the dangling `.rst_n(...)`. `external: true` is refused next to
    reset_port, so nothing can be inferred and the error points at `dut.reset`."""
    cfg = _with_port(_cfg(), "inputs", "arst")
    cfg["agents"][0]["reset_port"] = "arst"
    with pytest.raises(ValidationError, match="reset_port 'arst'") as e:
        ProjectConfig.model_validate(cfg)
    assert "dut.reset: arst" in str(e.value)
    cfg["dut"]["reset"] = "arst"
    ProjectConfig.model_validate(cfg)


def test_a_composed_leaf_gets_its_reset(tmp_path):
    """In a composition the same leaf config failed more quietly: the subsystem top
    gave the leaf's DUT a clock and NO reset connection at all (a floating reset
    port — it elaborates). The leaf's own inference is what connects it."""
    leaf = (
        "project: {{name: {n}}}\nlayout: packaged\n"
        "dut: {{name: {n}, clock: clk, reset: rst_n}}\n"
        "agents:\n  - name: {n}_a\n    interface: {n}_if\n"
        "    sequence_item: {n}_item\n    ports:\n"
        "      inputs: [{{name: din, width: 8}}]\n"
        "      outputs: [{{name: dout, width: 8, randomize: false}}]\n"
    )
    top = (
        "project: {name: sys}\nlayout: packaged\n"
        "dut: {name: sys, combinational: true, reset: ''}\n"
        "subenvs:\n  - {name: u_a, config: la.yaml}\n"
        "  - {name: u_b, config: lb.yaml}\n"
    )
    (tmp_path / "sys.yaml").write_text(top)
    (tmp_path / "la.yaml").write_text(leaf.format(n="la"))
    (tmp_path / "lb.yaml").write_text(leaf.format(n="lb"))
    cfg = ProjectConfig.from_yaml(tmp_path / "sys.yaml")
    out = tmp_path / "tb"
    Generator(cfg).generate_all(out, backup=False)
    top_sv = (out / "tb_top.sv").read_text()
    assert ".rst_n(u_a_rst_n)" in top_sv
    assert ".rst_n(u_b_rst_n)" in top_sv
    assert _gate(out) == []


# --- 3. the static check itself -----------------------------------------------

_IF = """
interface a_if (input clk);
  logic [7:0] din;
  clocking cb1 @(posedge clk);
    output din;
    input rst_n;
  endclocking
endinterface
"""


def _top(dut, pre=""):
    return (
        "module tb_top;\n  logic clk;\n"
        f"{pre}\n  a_if a_if_inst (clk);\n"
        "  // pragma quickuvm custom dut_connections begin\n"
        f"{dut}\n"
        "  // pragma quickuvm custom dut_connections end\nendmodule\n"
    )


def _lint(dut, pre="", iface=_IF):
    return find_dangling_dut_connections(
        _top(dut, pre), {"a_if.sv": iface}, "tb_top.sv"
    )


def test_flags_the_real_bug():
    """The exact shape that shipped: a signal the clocking block merely REFERENCES."""
    v = _lint(
        "  demo dut_inst (\n    .din(a_if_inst.din),\n    .rst_n(a_if_inst.rst_n)  );"
    )
    assert len(v) == 1, v
    assert "a_if" in v[0] and "rst_n" in v[0]


def test_accepts_a_declared_signal_net_and_parameter_list():
    v = _lint(
        "  demo #(.W(WIDTH), .D(4)) dut_inst (\n"
        "    .din(a_if_inst.din),\n    .clk(clk),\n    .rst_n(rst_n)  );",
        pre="  logic rst_n;",
    )
    assert v == []


def test_reference_inside_an_expression_is_still_checked():
    v = _lint(
        "  demo dut_inst (.rst_n(~(a_if_inst.rst_n)), .d({a_if_inst.din, 1'b0}));"
    )
    assert len(v) == 1, v


def test_an_assignment_is_not_a_declaration():
    """`begin` + newline + `rst_n = ...;` must not read as `<type> rst_n;`."""
    v = _lint(
        "  demo dut_inst (.rst_n(rst_n));",
        pre="  initial begin\n    rst_n = 1'b0;\n  end",
    )
    assert len(v) == 1, v


def test_an_initialiser_or_a_dimension_is_not_a_declaration():
    assert (
        len(_lint("  demo dut_inst (.rst_n(rst_n));", pre="  logic other = rst_n;"))
        == 1
    )
    v = _lint(
        "  demo dut_inst (.x(a_if_inst.W));",
        iface="interface a_if;\n  logic [W-1:0] d;\nendinterface\n",
    )
    assert len(v) == 1, v


def test_user_typed_signal_and_comma_lists_are_declared():
    iface = "interface a_if (input clk);\n  pkt_t pkt;\n  wire r1, r2;\nendinterface\n"
    assert (
        _lint("  demo dut_inst (.p(a_if_inst.pkt), .q(a_if_inst.r2));", iface=iface)
        == []
    )


def test_unknown_instance_is_a_violation_but_a_foreign_interface_is_skipped():
    assert len(_lint("  demo dut_inst (.x(ghost_inst.x));")) == 1
    # an interface generated elsewhere (a VIP by reference): no source to read
    top = _top("  demo dut_inst (.y(a_if_inst.din));")
    assert find_dangling_dut_connections(top, {}, "tb_top.sv") == []


def test_a_commented_out_connection_is_ignored():
    v = _lint(
        "  demo dut_inst (\n    // .rst_n(a_if_inst.rst_n),\n    .din(a_if_inst.din)  );"
    )
    assert v == []


# --- 4. every generated example -----------------------------------------------


def _example_configs() -> list[Path]:
    return sorted(
        (d / f"{d.name}.yaml")
        for d in _EXAMPLES.iterdir()
        if d.is_dir() and (d / f"{d.name}.yaml").exists()
    )


@pytest.mark.parametrize("cfg_file", _example_configs(), ids=lambda p: p.parent.name)
def test_generated_example_has_no_dangling_dut_connection(
    cfg_file: Path, tmp_path: Path
):
    """No example may generate a top that connects the DUT to a signal that does
    not exist. Runs on hosted CI, no licence."""
    cfg = ProjectConfig.from_yaml(cfg_file)
    Generator(cfg).generate_all(tmp_path, backup=False)

    violations = _gate(tmp_path)
    assert not violations, "\n".join(violations)
