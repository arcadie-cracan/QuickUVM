"""H1 — sub-environments (`subenvs:` composing >=2 child block envs).

A subsystem (top) bench references each child block's own config; the child's
reusable env layer is generated alongside a top layer (env / env_cfg / virtual
sequencer / vseq / test / tb_top / test_pkg) that composes them. Opt-in: a bench
with no `subenvs` is an ordinary bench (byte-identical).
"""

from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    ClockConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
)
from quick_uvm.models import (
    TestConfig as TConf,
)

SOC = Path(__file__).resolve().parents[1] / "examples" / "soc" / "soc.yaml"
PSOC = Path(__file__).resolve().parents[1] / "examples" / "psoc" / "psoc.yaml"
PIPE = Path(__file__).resolve().parents[1] / "examples" / "pipe" / "pipe.yaml"
CHANNELS = (
    Path(__file__).resolve().parents[1] / "examples" / "channels" / "channels.yaml"
)
NESTED = Path(__file__).resolve().parents[1] / "examples" / "nested" / "nested.yaml"
NSOC = Path(__file__).resolve().parents[1] / "examples" / "nsoc" / "nsoc.yaml"
XPIPE = Path(__file__).resolve().parents[1] / "examples" / "xpipe" / "xpipe.yaml"
DSOC = Path(__file__).resolve().parents[1] / "examples" / "dsoc" / "dsoc.yaml"
CSOC = Path(__file__).resolve().parents[1] / "examples" / "csoc" / "csoc.yaml"


def _block(name, agent, iface):
    return ProjectConfig(
        project=ProjectMeta(name=name),
        dut=DutConfig(name=name, combinational=True, reset=""),
        agents=[
            AgentConfig(
                name=agent,
                interface=iface,
                sequence_item=f"{agent}_seq_item",
                ports={"inputs": [PortConfig(name="din", width=8)]},
            )
        ],
        tests=[TConf(name=f"{name}_test")],
    )


def _top(layout="packaged", **extra):
    from quick_uvm.models import SubenvConfig

    return ProjectConfig(
        project=ProjectMeta(name="soc"),
        dut=DutConfig(name="soc", combinational=True, reset=""),
        agents=[],
        layout=layout,
        subenvs=[
            SubenvConfig(name="adder", config="adder/adder.yaml"),
            SubenvConfig(name="inverter", config="inverter/inverter.yaml"),
        ],
        tests=[TConf(name="soc_test")],
        **extra,
    )


# ---- loader (external config files, resolved relative to the top) -----------


def test_from_yaml_resolves_child_configs():
    top = ProjectConfig.from_yaml(SOC)
    assert [s.name for s in top.subenvs] == ["adder", "inverter"]
    assert set(top.subenv_configs) == {"adder", "inverter"}
    assert top.subenv_configs["adder"].dut.name == "adder"
    assert top.subenv_configs["inverter"].agents[0].interface == "b_if"
    views = top.subenv_views
    assert [v.block for v in views] == ["adder", "inverter"]
    assert views[0].env_pkg == "adder_env_pkg"


# ---- generation: child env layers + top composition -------------------------


def _gen(tmp_path):
    Generator(ProjectConfig.from_yaml(SOC)).generate_all(tmp_path)
    return tmp_path


def test_children_emit_env_layer_only(tmp_path):
    _gen(tmp_path)
    # each child's reusable env package + agent VIP
    for f in (
        "adder_env_pkg.sv",
        "a_pkg.sv",
        "a_if.sv",
        "adder_env.svh",
        "adder_scoreboard.svh",
        "inverter_env_pkg.sv",
        "b_pkg.sv",
    ):
        assert (tmp_path / f).exists(), f
    # but NOT a child test / tb_top / clkgen / DUT stub / test_pkg
    for f in (
        "adder_base_test.svh",
        "adder_test.svh",
        "adder.sv",
        "adder_test_pkg.sv",
        "inverter.sv",
    ):
        assert not (tmp_path / f).exists(), f


def test_top_env_composes_children(tmp_path):
    _gen(tmp_path)
    e = (tmp_path / "soc_env.svh").read_text()
    assert "adder_env adder;" in e  # handle != class name (no collision)
    assert "inverter_env inverter;" in e
    assert 'adder = adder_env::type_id::create("adder", this);' in e
    assert "vsqr.adder_a_sqr = adder.a_agnt.sqr;" in e
    assert "vsqr.inverter_b_sqr = inverter.b_agnt.sqr;" in e


def test_top_virtual_sequencer_collects_block_sequencers(tmp_path):
    _gen(tmp_path)
    v = (tmp_path / "soc_virtual_sequencer.svh").read_text()
    assert "a_sequencer adder_a_sqr;" in v
    assert "b_sequencer inverter_b_sqr;" in v


def test_top_vseq_forks_each_block(tmp_path):
    _gen(tmp_path)
    vs = (tmp_path / "soc_vseq.svh").read_text()
    assert "adder_a_seq.start(p_sequencer.adder_a_sqr);" in vs
    assert "inverter_b_seq.start(p_sequencer.inverter_b_sqr);" in vs
    assert "fork" in vs and "join" in vs


def test_top_base_test_populates_child_cfgs(tmp_path):
    _gen(tmp_path)
    bt = (tmp_path / "soc_base_test.svh").read_text()
    assert "env_cfg.adder_cfg = adder_env_cfg::type_id::create" in bt
    assert 'uvm_config_db#(adder_env_cfg)::set(this, "e.adder", "env_cfg"' in bt
    assert '"adder_a_if_vif"' in bt


def test_top_tb_top_instantiates_block_duts(tmp_path):
    _gen(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "a_if adder_a_if_inst (clk);" in top
    assert "b_if inverter_b_if_inst (clk);" in top
    assert "adder adder_dut (" in top
    assert "inverter inverter_dut (" in top
    assert '"adder_a_if_vif", adder_a_if_inst' in top


def test_top_test_pkg_imports_child_env_pkgs(tmp_path):
    _gen(tmp_path)
    pkg = (tmp_path / "soc_test_pkg.sv").read_text()
    assert "import adder_env_pkg::*;" in pkg
    assert "import inverter_env_pkg::*;" in pkg
    assert "import a_pkg::*;" in pkg


# ---- validation -------------------------------------------------------------


def test_subenvs_require_packaged_layout():
    with pytest.raises(Exception, match="layout: packaged"):
        _top(layout="flat")


def test_subenvs_allow_boundary_agents_but_fence_the_shapes():
    """H2 — a subsystem top MAY declare its own (boundary) agents; the flat-only
    shapes (responder / parameterized / replicated) stay fenced this slice."""
    from quick_uvm.models import SubenvConfig

    def _cfg(**agent_over):
        a = dict(
            name="x",
            interface="xi",
            sequence_item="xt",
            ports={"inputs": [PortConfig(name="din", width=8)]},
        )
        a.update(agent_over)
        return ProjectConfig(
            project=ProjectMeta(name="soc"),
            dut=DutConfig(name="soc", combinational=True, reset=""),
            layout="packaged",
            agents=[AgentConfig(**a)],
            subenvs=[
                SubenvConfig(name="a", config="a.yaml"),
                SubenvConfig(name="b", config="b.yaml"),
            ],
            tests=[TConf(name="t")],
        )

    _cfg()  # a plain boundary agent is now legal
    with pytest.raises(Exception, match="not supported at a subsystem top"):
        _cfg(
            mode="responder",
            request_valid="req",
            ports={
                "inputs": [PortConfig(name="gnt", width=1)],
                "outputs": [PortConfig(name="req", width=1)],
            },
        )
    # replicas on a boundary agent: rejected (whichever replicas wall fires first)
    with pytest.raises(Exception, match="replicas"):
        _cfg(replicas=3)


def test_subenvs_require_at_least_two():
    from quick_uvm.models import SubenvConfig

    with pytest.raises(Exception, match=">=2 child block envs"):
        ProjectConfig(
            project=ProjectMeta(name="soc"),
            dut=DutConfig(name="soc", combinational=True, reset=""),
            layout="packaged",
            subenvs=[SubenvConfig(name="only", config="only.yaml")],
            tests=[TConf(name="t")],
        )


def test_cross_child_name_collision_rejected():
    top = _top()
    # two blocks that both use agent name "a" / interface "same_if"
    top.subenv_configs = {
        "adder": _block("adder", "a", "same_if"),
        "inverter": _block("inverter", "a", "same_if"),
    }
    with pytest.raises(Exception, match="collides with another block"):
        top.validate_subenv_composition()


def test_child_dut_name_collision_rejected():
    top = _top()
    top.subenv_configs = {
        "adder": _block("dupblk", "a", "a_if"),
        "inverter": _block("dupblk", "b", "b_if"),
    }
    with pytest.raises(Exception, match="collides with another block or the top"):
        top.validate_subenv_composition()


def _clocked_block(name, agent, iface, period=10, unit="ns"):
    return ProjectConfig(
        project=ProjectMeta(name=name),
        dut=DutConfig(
            name=name, combinational=False, reset="rst_n", external_reset=True
        ),
        clock=ClockConfig(period=period, unit=unit),
        agents=[
            AgentConfig(
                name=agent,
                interface=iface,
                sequence_item=f"{agent}_seq_item",
                ports={
                    "inputs": [PortConfig(name="din", width=8)],
                    "outputs": [PortConfig(name="dout", width=8)],
                },
            )
        ],
        tests=[TConf(name=f"{name}_test")],
    )


def test_clocked_child_block_accepted():
    # H1 x M1: a clocked (registered, external-reset) child now composes fine.
    top = _top()
    top.subenv_configs = {
        "adder": _clocked_block("adder", "a", "a_if"),
        "inverter": _clocked_block("inverter", "b", "b_if", period=8),
    }
    top.validate_subenv_composition()  # must not raise


def test_clocked_leaf_mixed_unit_rejected():
    # a composed clocked leaf must share the subsystem's time unit (ns) in this slice.
    top = _top()
    top.subenv_configs = {
        "adder": _clocked_block("adder", "a", "a_if"),
        "inverter": _clocked_block("inverter", "b", "b_if", period=500, unit="ps"),
    }
    with pytest.raises(Exception, match="must share one time unit"):
        top.validate_subenv_composition()


def test_clocked_subsystem_tb_top_per_leaf_domains(tmp_path):
    # csoc composes two clocked leaves at DIFFERENT periods (acc @10ns, mul @8ns).
    # tb_top gets a pathname-prefixed clock + reset + clkgen + reset generator per leaf.
    Generator(ProjectConfig.from_yaml(CSOC)).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "logic acc_clk;" in top and "logic acc_rst_n;" in top
    assert "logic mul_clk;" in top and "logic mul_rst_n;" in top
    # one parameterized clkgen per leaf, at its own period
    assert "clkgen #(10) ck_acc_clk (acc_clk);" in top
    assert "clkgen #(8) ck_mul_clk (mul_clk);" in top
    # a reset generator per leaf, each synced to its own clock, own pragma region
    assert "// pragma quickuvm custom reset_generator_acc_rst_n begin" in top
    assert "repeat (5) @(posedge acc_clk);" in top
    assert "repeat (5) @(posedge mul_clk);" in top
    # each interface + DUT bound to its leaf's domain
    assert "a_if acc_a_if_inst (.clk(acc_clk), .rst_n(acc_rst_n));" in top
    assert ".clk(mul_clk)," in top and ".rst_n(mul_rst_n)" in top
    # a fully-combinational subsystem keeps the shared clkgen (no multi-domain block)
    assert "clkgen ck (clk);" not in top  # this subsystem is fully clocked


def test_clocked_subsystem_leaf_env_is_reset_gated(tmp_path):
    # the composed clocked leaf's own env layer is already clocked-ready: its interface
    # carries the reset port and its driver/monitor reset-gate.
    Generator(ProjectConfig.from_yaml(CSOC)).generate_all(tmp_path)
    assert (
        "interface a_if (input clk, input rst_n);" in (tmp_path / "a_if.sv").read_text()
    )
    assert "wait (vif.rst_n === 1'b1);" in (tmp_path / "a_driver.svh").read_text()
    assert "wait (vif.rst_n === 1'b1);" in (tmp_path / "a_monitor.svh").read_text()


_PORTS = "ports: {inputs: [{name: din, width: 8}], outputs: [{name: dout, width: 8}]}"


def _clk_leaf(name, ag, reset=True, clock_block="clock: {period: 10, unit: ns}"):
    r = ", reset: rst_n, external_reset: true" if reset else ", reset: ''"
    return (
        f"project: {{name: {name}}}\n"
        f"dut: {{name: {name}, clock: clk{r}}}\n"
        f"{clock_block}\n"
        "agents:\n"
        f"  - {{name: {ag}, interface: {ag}_if, sequence_item: {ag}_it, {_PORTS}}}\n"
        f"tests: [{{name: {name}_t}}]\n"
    )


def _comb_leaf(name, ag):
    return (
        f"project: {{name: {name}}}\n"
        f"dut: {{name: {name}, combinational: true, reset: ''}}\n"
        "agents:\n"
        f"  - {{name: {ag}, interface: {ag}_if, sequence_item: {ag}_it, {_PORTS}}}\n"
        f"tests: [{{name: {name}_t}}]\n"
    )


def _write_clocked_top(tmp_path, leaves):
    # leaves: list of (subenv_name, leaf_yaml_text)
    for name, text in leaves:
        (tmp_path / f"{name}.yaml").write_text(text)
    subs = "\n".join(f"  - {{name: {n}, config: {n}.yaml}}" for n, _ in leaves)
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: cs}\n"
        "layout: packaged\n"
        "dut: {name: cs, combinational: true, reset: ''}\n"
        "subenvs:\n" + subs + "\ntests: [{name: cs_t}]\n"
    )
    return top


def test_mixed_clocked_and_combinational_leaves(tmp_path):
    # a subsystem may mix a CLOCKED leaf and a COMBINATIONAL leaf: the clocked leaf
    # gets its own domain; the combinational leaf keeps the bare shared cadence `clk`.
    top = _write_clocked_top(
        tmp_path, [("acc", _clk_leaf("acc", "a")), ("cmb", _comb_leaf("cmb", "c"))]
    )
    Generator(ProjectConfig.from_yaml(top)).generate_all(tmp_path / "g")
    tb = (tmp_path / "g" / "tb_top.sv").read_text()
    assert "clkgen #(10) ck_acc_clk (acc_clk);" in tb  # clocked leaf's own clkgen
    assert "clkgen ck (clk);" in tb  # shared cadence for the combinational leaf
    assert "a_if acc_a_if_inst (.clk(acc_clk), .rst_n(acc_rst_n));" in tb
    assert "c_if cmb_c_if_inst (clk);" in tb  # combinational leaf: bare (clk)


def test_clock_only_leaf_has_no_reset(tmp_path):
    # a clocked leaf without external_reset gets a clock but NO reset net/generator.
    top = _write_clocked_top(
        tmp_path,
        [("acc", _clk_leaf("acc", "a", reset=False)), ("mul", _clk_leaf("mul", "m"))],
    )
    Generator(ProjectConfig.from_yaml(top)).generate_all(tmp_path / "g")
    tb = (tmp_path / "g" / "tb_top.sv").read_text()
    assert "clkgen #(10) ck_acc_clk (acc_clk);" in tb
    assert "reset_generator_acc_rst_n" not in tb  # no reset for the reset-less leaf
    assert "a_if acc_a_if_inst (.clk(acc_clk));" in tb  # no reset port bound
    assert "reset_generator_mul_rst_n" in tb  # the other leaf still has its reset


def test_clocked_leaf_multi_clock_rejected(tmp_path):
    multi = "clock:\n  - {name: clk, period: 10}\n  - {name: clk2, period: 8}"
    top = _write_clocked_top(
        tmp_path,
        [
            ("acc", _clk_leaf("acc", "a", clock_block=multi)),
            ("mul", _clk_leaf("mul", "m")),
        ],
    )
    with pytest.raises(Exception, match="must be single-clock"):
        ProjectConfig.from_yaml(top)


def test_leaf_pathname_collision_rejected(tmp_path):
    # a direct leaf-instance `a_b` and a subsystem `a` containing leaf `b` both flatten
    # to pathname `a_b` → duplicate tb_top nets/instances; rejected fail-closed.
    (tmp_path / "lf1.yaml").write_text(_comb_leaf("lf1", "g1"))
    (tmp_path / "lf2.yaml").write_text(_comb_leaf("lf2", "g2"))
    (tmp_path / "lf3.yaml").write_text(_comb_leaf("lf3", "g3"))
    (tmp_path / "clu.yaml").write_text(
        "project: {name: clu}\n"
        "layout: packaged\n"
        "dut: {name: clu, combinational: true, reset: ''}\n"
        "subenvs:\n  - {name: b, config: lf2.yaml}\n  - {name: d, config: lf3.yaml}\n"
        "tests: [{name: clu_t}]\n"
    )
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: topx}\n"
        "layout: packaged\n"
        "dut: {name: topx, combinational: true, reset: ''}\n"
        "subenvs:\n  - {name: a_b, config: lf1.yaml}\n  - {name: a, config: clu.yaml}\n"
        "tests: [{name: topx_t}]\n"
    )
    with pytest.raises(Exception, match="flatten to the same path"):
        ProjectConfig.from_yaml(top)


def test_single_agent_parameterized_child_allowed():
    # H1 param propagation: a single-agent parameterized block is now OK.
    from quick_uvm.models import ParamConfig

    top = _top()
    top.subenv_configs = {
        "adder": _block("adder", "a", "a_if"),
        "inverter": ProjectConfig(
            project=ProjectMeta(name="pblk"),
            dut=DutConfig(name="pblk", combinational=True, reset=""),
            agents=[
                AgentConfig(
                    name="p",
                    interface="p_if",
                    sequence_item="p_seq_item",
                    parameters=[ParamConfig(name="W", default=8)],
                    ports={"inputs": [PortConfig(name="din", width_param="W")]},
                )
            ],
            tests=[TConf(name="p_test")],
        ),
    }
    top.validate_subenv_composition()  # no raise


def test_multi_agent_parameterized_child_rejected():
    from quick_uvm.models import ParamConfig

    top = _top()
    multi = ProjectConfig(
        project=ProjectMeta(name="pblk"),
        dut=DutConfig(name="pblk", combinational=True, reset=""),
        auto_virtual_sequences=False,
        agents=[
            AgentConfig(
                name="p",
                interface="p_if",
                sequence_item="p_seq_item",
                parameters=[ParamConfig(name="W", default=8)],
                ports={"inputs": [PortConfig(name="din", width_param="W")]},
            ),
            AgentConfig(
                name="q",
                interface="q_if",
                sequence_item="q_seq_item",
                ports={"inputs": [PortConfig(name="qin", width=8)]},
            ),
        ],
        tests=[TConf(name="p_test")],
    )
    top.subenv_configs = {"adder": _block("adder", "a", "a_if"), "inverter": multi}
    with pytest.raises(Exception, match="must be single-agent"):
        top.validate_subenv_composition()


def test_top_analysis_scoreboards_route_to_cross_block():
    """The analysis unification: on a composition, `analysis.scoreboards` ARE the
    cross-block scoreboards (routed to the same machinery); coverage stays fenced,
    and the flat-only knobs are fenced per entry."""
    from quick_uvm.models import AnalysisConfig, ScoreboardSpec

    top = _top(
        analysis=AnalysisConfig(
            scoreboards=[
                ScoreboardSpec(name="chk", source="adder.a", monitor="inverter.b")
            ]
        )
    )
    assert [(s.name, s.source, s.monitor) for s in top.subenv_scoreboards] == [
        ("chk", "adder.a", "inverter.b")
    ]
    with pytest.raises(Exception, match="does not wire `analysis.coverage`"):
        _top(analysis=AnalysisConfig(coverage=["a"]))
    with pytest.raises(Exception, match="two-stream"):
        _top(
            analysis=AnalysisConfig(
                scoreboards=[ScoreboardSpec(name="chk", source="adder.a")]
            )
        )
    with pytest.raises(Exception, match="not supported on a composition"):
        _top(
            analysis=AnalysisConfig(
                scoreboards=[
                    ScoreboardSpec(
                        name="chk",
                        source="adder.a",
                        monitor="inverter.b",
                        match="out_of_order",
                        match_key="id",
                    )
                ]
            )
        )


def test_old_subenv_scoreboards_key_errors_with_move_hint(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(
        "project: {name: soc}\n"
        "layout: packaged\n"
        "dut: {name: soc, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: a, config: a.yaml}\n"
        "  - {name: b, config: b.yaml}\n"
        "subenv_scoreboards: [{name: c, source: a.x, monitor: b.y}]\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="moved under `analysis.scoreboards`"):
        ProjectConfig.from_yaml(p)


def test_generate_without_loaded_children_errors():
    # A top constructed in-memory (not via from_yaml) has no loaded children.
    with pytest.raises(Exception, match="child configs are not loaded"):
        Generator(_top()).files_to_generate()


# ---- H1 nested subenvs (a subsystem of sub-subsystems) ----------------------


def test_nested_loads_and_flattens_the_tree():
    top = ProjectConfig.from_yaml(NESTED)
    # direct children are subsystems (clusters), not leaf blocks
    assert [sv.name for sv in top.subenv_views] == ["cA", "cB"]
    assert all(sv.is_subsystem for sv in top.subenv_views)
    # leaf_views flatten the whole tree (path from top to leaf)
    assert [lv.path for lv in top.leaf_views] == [
        ["cA", "pa"],
        ["cA", "qa"],
        ["cB", "pb"],
        ["cB", "qb"],
    ]
    assert [lv.dut_module for lv in top.leaf_views] == ["a0", "a1", "b0", "b1"]
    # composition levels: clusters then the top (deepest-first)
    assert [c.dut.name for c in top.composition_levels] == [
        "clusterA",
        "clusterB",
        "nested",
    ]


def _ngen(tmp_path):
    Generator(ProjectConfig.from_yaml(NESTED)).generate_all(tmp_path)
    return tmp_path


def test_nested_top_composes_clusters_hierarchically(tmp_path):
    _ngen(tmp_path)
    e = (tmp_path / "nested_env.svh").read_text()
    assert "clusterA_env cA;" in e
    assert "clusterB_env cB;" in e
    assert 'cA = clusterA_env::type_id::create("cA", this);' in e
    assert "vsqr.cA_vsqr = cA.vsqr;" in e  # top holds cluster vsqrs (hierarchical)
    v = (tmp_path / "nested_virtual_sequencer.svh").read_text()
    assert "clusterA_virtual_sequencer cA_vsqr;" in v
    vs = (tmp_path / "nested_vseq.svh").read_text()
    assert "cA_seq.start(p_sequencer.cA_vsqr);" in vs  # top runs cluster vseqs


def test_nested_cluster_composes_leaf_blocks(tmp_path):
    _ngen(tmp_path)
    e = (tmp_path / "clusterA_env.svh").read_text()
    assert "a0_env pa;" in e
    assert "a1_env qa;" in e
    assert "vsqr.pa_ga0_sqr = pa.ga0_agnt.sqr;" in e  # cluster collects leaf agents


def test_nested_base_test_builds_config_tree(tmp_path):
    _ngen(tmp_path)
    bt = (tmp_path / "nested_base_test.svh").read_text()
    # cluster cfg set at its path; leaf cfg nested under it, at its deeper path
    assert 'uvm_config_db#(clusterA_env_cfg)::set(this, "e.cA", "env_cfg"' in bt
    assert "env_cfg.cA_cfg.pa_cfg = a0_env_cfg::type_id::create" in bt
    assert 'uvm_config_db#(a0_env_cfg)::set(this, "e.cA.pa", "env_cfg"' in bt
    assert '"cA_pa_ga0_if_vif"' in bt  # full-path vif key


def test_nested_tb_top_instantiates_all_leaf_duts(tmp_path):
    _ngen(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "ga0_if cA_pa_ga0_if_inst (clk);" in top
    assert "a0 cA_pa_dut (" in top  # unprefixed leaf RTL module, path-named inst
    assert "b1 cB_qb_dut (" in top
    pkg = (tmp_path / "nested_test_pkg.sv").read_text()
    assert "import a0_env_pkg::*;" in pkg  # flattened leaf pkg imports
    assert '`include "clusterA_env.svh"' in pkg  # cluster composition class included


def test_connection_naming_subsystem_directly_rejected(tmp_path):
    # A cross-level endpoint must descend to a LEAF block: naming a subsystem
    # directly (cA.dout, where cA is a cluster) is rejected — you must reach an
    # inner leaf (cA.<leaf>.dout). (Cross-level into a leaf is supported; see
    # test_cross_level_connection_resolves_into_nested_leaf.)
    from quick_uvm.models import ProjectConfig as PC

    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: t}\n"
        "layout: packaged\n"
        "dut: {name: t, combinational: true, reset: ''}\n"
        "subenvs:\n"
        f"  - {{name: cA, config: {NESTED.parent / 'clusterA.yaml'}}}\n"
        f"  - {{name: cB, config: {NESTED.parent / 'clusterB.yaml'}}}\n"
        "connections: [{from: cA.dout, to: cB.din}]\n"  # cA is a subsystem
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="is a subsystem, not a leaf"):
        PC.from_yaml(top)


# ---- H1 cross-LEVEL connections + scoreboards (into nested leaves) -----------


def test_cross_level_connection_resolves_into_nested_leaf():
    # xpipe: a top wire reaches into two clusters — stg1.add.dout -> stg2.inv.din.
    top = ProjectConfig.from_yaml(XPIPE)
    assert top.all_resolved_connections == [
        {"dst": "stg2_inv_b_if_inst.din", "src": "stg1_add_a_if_inst.dout"}
    ]


def test_cross_level_scoreboard_handle_chain():
    # the cross-level scoreboard's endpoints resolve to dotted child-env handle
    # chains (declaring-level-relative): stg1.add / stg2.inv, agents a / b.
    top = ProjectConfig.from_yaml(XPIPE)
    sb = top.subenv_scoreboards[0]
    s_h, s_ag, m_h, m_ag = top.cross_block_sb_endpoints(sb)
    assert (s_h, s_ag.name, m_h, m_ag.name) == ("stg1.add", "a", "stg2.inv", "b")


def test_cross_level_tb_top_and_env_emitted(tmp_path):
    Generator(ProjectConfig.from_yaml(XPIPE)).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    # the flattened cross-level wire, with the real leaf interface instances present
    assert "assign stg2_inv_b_if_inst.din = stg1_add_a_if_inst.dout;" in top
    assert "a_if stg1_add_a_if_inst (clk);" in top
    assert "b_if stg2_inv_b_if_inst (clk);" in top
    e = (tmp_path / "xpipe_env.svh").read_text()
    # the dotted handle chain reaches the nested leaf agents' analysis ports
    assert "stg1.add.a_agnt.ap.connect(xchk.src_axp);" in e
    assert "stg2.inv.b_agnt.ap.connect(xchk.mon_axp);" in e


def test_cross_level_double_drive_rejected(tmp_path):
    # A nested leaf input driven by TWO wires at different levels (a cluster's own
    # internal wire AND an ancestor's cross-level wire) must be caught, even though
    # each spells the destination differently relative to its own level — otherwise
    # tb_top emits two `assign`s to one net (multiply-driven).
    from quick_uvm.models import ProjectConfig as PC

    # p: active source; q: passive sink (driven by a wire); ext: active source
    (tmp_path / "p.yaml").write_text(
        "project: {name: p}\n"
        "dut: {name: p, combinational: true, reset: ''}\n"
        "agents:\n"
        "  - {name: pa, interface: p_if, sequence_item: p_item,\n"
        "     ports: {inputs: [{name: din, width: 8}], outputs: [{name: dout, width: 8}]}}\n"
        "tests: [{name: p_t}]\n"
    )
    (tmp_path / "q.yaml").write_text(
        "project: {name: q}\n"
        "dut: {name: q, combinational: true, reset: ''}\n"
        "agents:\n"
        "  - {name: qa, interface: q_if, sequence_item: q_item, active: false,\n"
        "     ports: {inputs: [{name: din, width: 8}], outputs: [{name: dout, width: 8}]}}\n"
        "tests: [{name: q_t}]\n"
    )
    (tmp_path / "ext.yaml").write_text(
        "project: {name: ext}\n"
        "dut: {name: ext, combinational: true, reset: ''}\n"
        "agents:\n"
        "  - {name: ea, interface: e_if, sequence_item: e_item,\n"
        "     ports: {inputs: [{name: din, width: 8}], outputs: [{name: dout, width: 8}]}}\n"
        "tests: [{name: e_t}]\n"
    )
    # mid drives its OWN leaf input internally: p.dout -> q.din
    (tmp_path / "mid.yaml").write_text(
        "project: {name: mid}\n"
        "layout: packaged\n"
        "dut: {name: mid, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: p, config: p.yaml}\n"
        "  - {name: q, config: q.yaml}\n"
        "connections: [{from: p.dout, to: q.din}]\n"
        "tests: [{name: mid_t}]\n"
    )
    # the top ALSO drives the same physical input via a cross-level wire: ext.dout -> mid.q.din
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: topd}\n"
        "layout: packaged\n"
        "dut: {name: topd, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: mid, config: mid.yaml}\n"
        "  - {name: ext, config: ext.yaml}\n"
        "connections: [{from: ext.dout, to: mid.q.din}]\n"
        "tests: [{name: topd_t}]\n"
    )
    with pytest.raises(Exception, match="multiple connections drive"):
        PC.from_yaml(top)


def test_scoreboard_declared_at_nested_cluster_emitted(tmp_path):
    # "any level": a nested CLUSTER declares its OWN scoreboard over its leaves;
    # it resolves relative to that cluster and the cluster's env (not the top)
    # emits the connect. The top just composes the clusters.
    from quick_uvm.models import ProjectConfig as PC

    # four distinct leaves (unique across the flattened tree)
    for blk, agent, iface in (
        ("p", "pa", "pa_if"),
        ("q", "qa", "qa_if"),
        ("r", "ra", "ra_if"),
        ("s", "sa", "sa_if"),
    ):
        (tmp_path / f"{blk}.yaml").write_text(
            f"project: {{name: {blk}}}\n"
            f"dut: {{name: {blk}, combinational: true, reset: ''}}\n"
            "agents:\n"
            f"  - name: {agent}\n"
            f"    interface: {iface}\n"
            f"    sequence_item: {agent}_item\n"
            "    ports:\n"
            "      inputs:  [{name: din,  width: 8}]\n"
            "      outputs: [{name: dout, width: 8}]\n"
            f"tests: [{{name: {blk}_t}}]\n"
        )
    # the nested cluster owns the scoreboard (same-level over its own p/q leaves)
    (tmp_path / "sub.yaml").write_text(
        "project: {name: sub}\n"
        "layout: packaged\n"
        "dut: {name: sub, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: p, config: p.yaml}\n"
        "  - {name: q, config: q.yaml}\n"
        "analysis: {scoreboards: [{name: nsb, source: p.pa, monitor: q.qa}]}\n"
        "tests: [{name: sub_t}]\n"
    )
    # a distinct second cluster (r + s, no scoreboard) so the top composes >=2
    (tmp_path / "sub2.yaml").write_text(
        "project: {name: sub2}\n"
        "layout: packaged\n"
        "dut: {name: sub2, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: r, config: r.yaml}\n"
        "  - {name: s, config: s.yaml}\n"
        "tests: [{name: sub2_t}]\n"
    )
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: topx}\n"
        "layout: packaged\n"
        "dut: {name: topx, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: s1, config: sub.yaml}\n"
        "  - {name: s2, config: sub2.yaml}\n"
        "tests: [{name: topx_t}]\n"
    )
    cfg = PC.from_yaml(top)
    sub_cfg = cfg.subenv_configs["s1"]
    s_h, s_ag, m_h, m_ag = sub_cfg.cross_block_sb_endpoints(
        sub_cfg.subenv_scoreboards[0]
    )
    assert (s_h, s_ag.name, m_h, m_ag.name) == ("p", "pa", "q", "qa")
    Generator(cfg).generate_all(tmp_path / "gen")
    sub_env = (tmp_path / "gen" / "sub_env.svh").read_text()
    assert "p.pa_agnt.ap.connect(nsb.src_axp);" in sub_env
    assert "q.qa_agnt.ap.connect(nsb.mon_axp);" in sub_env


# ---- H1 parameterized / reused nested subsystems ---------------------------


def test_reused_cluster_namespaced_and_parameterized_recursively():
    top = ProjectConfig.from_yaml(NSOC)
    # the SAME chan cluster reused as lo/hi -> its whole subtree is prefixed
    assert [c.dut.name for c in top.composition_levels] == [
        "lo_chan",
        "hi_chan",
        "nsoc",
    ]
    lv = {tuple(v.path): v for v in top.leaf_views}
    # grandchild leaf classes are prefixed per instance (no collision)...
    assert lv[("lo", "adder")].agents[0].name == "lo_a"
    assert lv[("hi", "adder")].agents[0].name == "hi_a"
    assert lv[("lo", "adder")].agents[0].interface == "lo_a_if"
    # ...but the reused RTL DUT module is recovered UNprefixed (original name)
    assert lv[("lo", "adder")].dut_module == "add"
    assert lv[("hi", "adder")].dut_module == "add"
    assert lv[("lo", "shifter")].dut_module == "shl"
    # the width is BROADCAST down to the grandchild agents
    assert lv[("lo", "adder")].agents[0].param_args_values == "#(8)"
    assert lv[("hi", "adder")].agents[0].param_args_values == "#(16)"
    assert lv[("hi", "shifter")].agents[0].param_args_values == "#(16)"


def test_reused_parameterized_cluster_generates(tmp_path):
    Generator(ProjectConfig.from_yaml(NSOC)).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    # reused unprefixed RTL modules at the propagated widths
    assert "add#(8) lo_adder_dut (" in top
    assert "add#(16) hi_adder_dut (" in top
    assert "shl#(16) hi_shifter_dut (" in top
    # distinct, prefixed cluster env classes — no collision between lo/hi
    assert (tmp_path / "lo_chan_env.svh").exists()
    assert (tmp_path / "hi_chan_env.svh").exists()
    assert (tmp_path / "lo_add_env.svh").exists()
    txn = (tmp_path / "hi_a_item.svh").read_text()
    assert "class hi_a_item #(parameter int W = 16)" in txn  # propagated width


def test_param_key_matching_no_descendant_agent_rejected(tmp_path):
    # A params key that no descendant agent declares must error (fail-closed).
    from quick_uvm.models import ProjectConfig as PC

    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: t}\n"
        "layout: packaged\n"
        "dut: {name: t, combinational: true, reset: ''}\n"
        "subenvs:\n"
        f"  - {{name: lo, config: {NSOC.parent / 'chan.yaml'}, params: {{ZZ: 4}}}}\n"
        f"  - {{name: hi, config: {NSOC.parent / 'chan.yaml'}, params: {{W: 16}}}}\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="not a declared parameter of any agent"):
        PC.from_yaml(top)


# ---- H1 same-block-reused-at-N-widths (namespacing) ------------------------


def _mkblock(tmp_path, name="chan"):
    """Write a minimal parameterized block config + return the dir for a top."""
    d = tmp_path / name
    d.mkdir()
    (d / f"{name}.yaml").write_text(
        f"project: {{name: {name}}}\n"
        f"dut: {{name: {name}, combinational: true, reset: ''}}\n"
        "agents:\n"
        "  - name: c\n"
        "    interface: c_if\n"
        "    sequence_item: c_seq_item\n"
        "    parameters: [{name: W, default: 8}]\n"
        "    ports:\n"
        "      inputs:  [{name: din,  width_param: W}]\n"
        "      outputs: [{name: dout, width_param: W}]\n"
        "tests: [{name: t}]\n"
    )
    return f"{name}/{name}.yaml"


def _write_top(tmp_path, subenvs_yaml):
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: top}\n"
        "layout: packaged\n"
        "dut: {name: top, combinational: true, reset: ''}\n"
        f"subenvs:\n{subenvs_yaml}\n"
        "tests: [{name: top_test}]\n"
    )
    return top


def test_shared_config_auto_namespaced():
    top = ProjectConfig.from_yaml(CHANNELS)
    assert top.subenv_namespaces == {"lo": "lo", "hi": "hi"}
    lo, hi = top.subenv_views
    assert lo.block == "lo_chan" and hi.block == "hi_chan"
    assert lo.cfg.agents[0].interface == "lo_c_if"
    assert hi.cfg.agents[0].sequence_item == "hi_c_seq_item"
    assert lo.cfg.agents[0].param_args_values == "#(8)"
    assert hi.cfg.agents[0].param_args_values == "#(16)"
    # the reused RTL DUT module name is UNprefixed
    assert lo.dut_module == "chan" and hi.dut_module == "chan"


def test_distinct_configs_not_namespaced():
    top = ProjectConfig.from_yaml(SOC)
    assert top.subenv_namespaces == {"adder": "", "inverter": ""}
    assert all(not v.namespaced for v in top.subenv_views)
    assert top.subenv_views[0].dut_module == "adder"  # == block when not namespaced


def test_namespaced_classes_generated(tmp_path):
    Generator(ProjectConfig.from_yaml(CHANNELS)).generate_all(tmp_path)
    # one config, two fully-namespaced class sets — no collision
    for f in (
        "lo_chan_env.svh",
        "lo_c_seq_item.svh",
        "lo_chan_env_pkg.sv",
        "hi_chan_env.svh",
        "hi_c_seq_item.svh",
        "hi_chan_env_pkg.sv",
    ):
        assert (tmp_path / f).exists(), f
    txn = (tmp_path / "hi_c_seq_item.svh").read_text()
    assert "class hi_c_seq_item #(parameter int W = 16)" in txn  # propagated width
    top = (tmp_path / "tb_top.sv").read_text()
    # reused unprefixed DUT module, instantiated at each width
    assert "chan#(8) lo_dut (" in top
    assert "chan#(16) hi_dut (" in top
    assert "lo_c_if#(8) lo_lo_c_if_inst (clk);" in top


def test_explicit_namespace_overrides(tmp_path):
    from quick_uvm.models import ProjectConfig as PC

    cfg = _mkblock(tmp_path)
    # namespace: true forces prefixing even for a single (non-shared) use
    top = _write_top(
        tmp_path,
        f"  - {{name: only, config: {cfg}, namespace: true}}\n"
        f"  - {{name: two, config: {_mkblock(tmp_path, 'blk2')}}}",
    )
    c = PC.from_yaml(top)
    assert c.subenv_namespaces["only"] == "only"  # forced
    assert c.subenv_namespaces["two"] == ""  # single-use, not forced


def test_explicit_namespace_custom_prefix(tmp_path):
    from quick_uvm.models import ProjectConfig as PC

    cfg = _mkblock(tmp_path)
    top = _write_top(
        tmp_path,
        f"  - {{name: a, config: {cfg}, namespace: chX}}\n"
        f"  - {{name: b, config: {_mkblock(tmp_path, 'blk2')}}}",
    )
    c = PC.from_yaml(top)
    assert c.subenv_namespaces["a"] == "chX"
    assert c.subenv_configs["a"].dut.name == "chX_chan"


def test_cross_block_sequence_name_collision_rejected():
    # Two DISTINCT blocks that each declare a sequence named "burst" would both
    # emit burst.svh — the composition guard must reject it (fail-closed).
    from quick_uvm.models import SequenceConfig

    top = _top()
    a = _block("adder", "a", "a_if")
    a.agents[0].sequences = [SequenceConfig(name="burst")]
    b = _block("inverter", "b", "b_if")
    b.agents[0].sequences = [SequenceConfig(name="burst")]
    top.subenv_configs = {"adder": a, "inverter": b}
    with pytest.raises(Exception, match="sequence 'burst' collides"):
        top.validate_subenv_composition()


def test_namespace_false_collision_hint(tmp_path):
    # Disabling namespacing on a REUSED config surfaces a guided error.
    from quick_uvm.models import ProjectConfig as PC

    cfg = _mkblock(tmp_path)
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: top}\n"
        "layout: packaged\n"
        "dut: {name: top, combinational: true, reset: ''}\n"
        "subenvs:\n"
        f"  - {{name: lo, config: {cfg}, namespace: false, params: {{W: 8}}}}\n"
        f"  - {{name: hi, config: {cfg}, namespace: false, params: {{W: 16}}}}\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="namespacing is disabled"):
        PC.from_yaml(top)


# ---- H1 cross-level into a REUSED (namespaced) subtree ----------------------


def test_agent_original_name_captured_under_reuse():
    # _apply_namespace_prefix captures each agent's original name (idempotent), so a
    # cross-level endpoint can name a reused leaf agent as originally declared.
    top = ProjectConfig.from_yaml(DSOC)
    left = top.subenv_configs["left"]  # a namespaced lane instance
    src_leaf = left.subenv_configs["src"]
    a = src_leaf.agents[0]
    assert (a.name, a.original_name) == ("left_sa", "sa")


def test_reused_cross_level_wires_resolve_into_namespaced_instances():
    # dsoc rings the two reused lane instances: each src drives the OTHER lane's snk.
    top = ProjectConfig.from_yaml(DSOC)
    assert top.all_resolved_connections == [
        {
            "dst": "right_snk_right_snk_if_inst.din",
            "src": "left_src_left_src_if_inst.dout",
        },
        {
            "dst": "left_snk_left_snk_if_inst.din",
            "src": "right_src_right_src_if_inst.dout",
        },
    ]


def test_reused_cross_level_scoreboard_uses_original_agent_names():
    # the endpoint names the agent by its ORIGINAL name (sa/ka); the resolved handle
    # carries the auto-applied prefix (left_sa / right_ka).
    top = ProjectConfig.from_yaml(DSOC)
    l2r = next(sb for sb in top.subenv_scoreboards if sb.name == "l2r")
    s_h, s_ag, m_h, m_ag = top.cross_block_sb_endpoints(l2r)
    assert (s_h, s_ag.name, m_h, m_ag.name) == (
        "left.src",
        "left_sa",
        "right.snk",
        "right_ka",
    )


def test_reused_cross_level_tb_top_and_env_emitted(tmp_path):
    Generator(ProjectConfig.from_yaml(DSOC)).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    # ring wires between the namespaced leaf interface instances
    assert (
        "assign right_snk_right_snk_if_inst.din = left_src_left_src_if_inst.dout;"
        in top
    )
    assert (
        "assign left_snk_left_snk_if_inst.din = right_src_right_src_if_inst.dout;"
        in top
    )
    e = (tmp_path / "dsoc_env.svh").read_text()
    # the dotted handle chain carries the prefix on the agent handle (left_sa_agnt)
    assert "left.src.left_sa_agnt.ap.connect(l2r.src_axp);" in e
    assert "right.snk.right_ka_agnt.ap.connect(l2r.mon_axp);" in e


def test_reused_cross_level_unknown_original_agent_rejected(tmp_path):
    # a trailing token that matches neither the original nor the prefixed name is
    # still rejected (fail-closed) even into a reused subtree.
    from quick_uvm.models import ProjectConfig as PC

    for blk, agent, iface, active in (
        ("src", "sa", "src_if", "true"),
        ("snk", "ka", "snk_if", "false"),
    ):
        (tmp_path / f"{blk}.yaml").write_text(
            f"project: {{name: {blk}}}\n"
            f"dut: {{name: {blk}, combinational: true, reset: ''}}\n"
            "agents:\n"
            f"  - {{name: {agent}, interface: {iface}, sequence_item: {agent}_item,"
            f" active: {active},\n"
            "     ports: {inputs: [{name: din, width: 8}], outputs: [{name: dout, width: 8}]}}\n"
            f"tests: [{{name: {blk}_t}}]\n"
        )
    (tmp_path / "lane.yaml").write_text(
        "project: {name: lane}\n"
        "layout: packaged\n"
        "dut: {name: lane, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: src, config: src.yaml}\n"
        "  - {name: snk, config: snk.yaml}\n"
        "tests: [{name: lane_t}]\n"
    )
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: dt}\n"
        "layout: packaged\n"
        "dut: {name: dt, combinational: true, reset: ''}\n"
        "subenvs:\n"
        "  - {name: left, config: lane.yaml}\n"
        "  - {name: right, config: lane.yaml}\n"
        # 'nope' is neither the original (sa) nor the prefixed (left_sa) agent name
        "analysis: {scoreboards: [{name: b, source: left.src.nope, monitor: right.snk.ka}]}\n"
        "tests: [{name: dt_t}]\n"
    )
    with pytest.raises(Exception, match="has no agent 'nope'"):
        PC.from_yaml(top)


# ---- H1 parameter propagation ----------------------------------------------


def test_param_override_baked_into_child_defaults():
    top = ProjectConfig.from_yaml(PSOC)
    dp = top.subenv_configs["dp"]
    mac = top.subenv_configs["mac"]
    assert dp.agents[0].parameters[0].default == 8
    assert mac.agents[0].parameters[0].default == 16  # overridden from 8
    assert dp.agents[0].param_args_values == "#(8)"
    assert mac.agents[0].param_args_values == "#(16)"


def test_param_propagation_threads_widths_into_top(tmp_path):
    Generator(ProjectConfig.from_yaml(PSOC)).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "d_if#(8) dp_d_if_inst (clk);" in top
    assert "m_if#(16) mac_m_if_inst (clk);" in top
    assert "dp#(8) dp_dut (" in top
    assert "mac#(16) mac_dut (" in top
    assert "uvm_config_db#(virtual d_if#(8))::set" in top
    assert "uvm_config_db#(virtual m_if#(16))::set" in top
    vsqr = (tmp_path / "psoc_virtual_sequencer.svh").read_text()
    assert "d_sequencer#(8) dp_d_sqr;" in vsqr
    assert "m_sequencer#(16) mac_m_sqr;" in vsqr
    vseq = (tmp_path / "psoc_vseq.svh").read_text()
    assert "d_seq#(8) dp_d_seq;" in vseq
    assert "m_seq#(16) mac_m_seq;" in vseq
    bt = (tmp_path / "psoc_base_test.svh").read_text()
    assert "d_cfg#(8)::type_id::create" in bt
    assert "uvm_config_db#(virtual m_if#(16))::get(" in bt
    # each block's scoreboard is typed at its propagated width
    assert (
        "uvm_subscriber #(d_seq_item#(8))"
        in (tmp_path / "dp_predictor.svh").read_text()
    )
    assert (
        "uvm_subscriber #(m_seq_item#(16))"
        in (tmp_path / "mac_predictor.svh").read_text()
    )


# ---- H1 cross-block connections + scoreboards ------------------------------


def test_from_yaml_loads_connections_and_scoreboards():
    top = ProjectConfig.from_yaml(PIPE)
    assert [(c.src, c.dst) for c in top.connections] == [("add.dout", "inv.din")]
    assert [(s.source, s.monitor) for s in top.subenv_scoreboards] == [
        ("add.a", "inv.b")
    ]
    # resolution to top-level interface signals
    assert top.resolved_connections == [
        {"dst": "inv_b_if_inst.din", "src": "add_a_if_inst.dout"}
    ]


def _pgen(tmp_path):
    Generator(ProjectConfig.from_yaml(PIPE)).generate_all(tmp_path)
    return tmp_path


def test_tb_top_emits_cross_block_connection(tmp_path):
    _pgen(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "assign inv_b_if_inst.din = add_a_if_inst.dout;" in top


def test_cross_block_scoreboard_wired_in_top_env(tmp_path):
    _pgen(tmp_path)
    e = (tmp_path / "pipe_env.svh").read_text()
    assert "pipe_chk_scoreboard chk;" in e
    assert 'chk = pipe_chk_scoreboard::type_id::create("chk", this);' in e
    assert "add.a_agnt.ap.connect(chk.src_axp);" in e
    assert "inv.b_agnt.ap.connect(chk.mon_axp);" in e


def test_cross_block_predictor_typed_source_to_monitor(tmp_path):
    _pgen(tmp_path)
    p = (tmp_path / "pipe_chk_predictor.svh").read_text()
    assert "uvm_subscriber #(a_seq_item)" in p  # source stream
    assert "uvm_analysis_port #(b_seq_item)" in p  # monitor/expected stream
    assert "predict(a_seq_item t)" in p
    pkg = (tmp_path / "pipe_test_pkg.sv").read_text()
    assert '`include "pipe_chk_predictor.svh"' in pkg
    assert '`include "pipe_chk_reference_model.svh"' in pkg


def test_passive_agent_input_is_monitored_not_driven(tmp_path):
    # The passive inv block: its input port is a sampled clockvar (input), and its
    # driver drives nothing — so the top connection can drive it without conflict.
    _pgen(tmp_path)
    bif = (tmp_path / "b_if.sv").read_text()
    assert "input  din;" in bif  # driver cb1 samples, not `output din`
    drv = (tmp_path / "b_driver.svh").read_text()
    assert "vif.cb1.din <=" not in drv  # passive driver drives nothing


def test_connection_to_active_agent_rejected():
    # A connection cannot drive an ACTIVE agent's input (the agent already drives it).
    from quick_uvm.models import SubenvConnection

    top = _top()
    src = _block("adder", "a", "a_if")
    src.agents[0].ports["outputs"] = [PortConfig(name="dout", width=8)]
    top.subenv_configs = {"adder": src, "inverter": _block("inverter", "b", "b_if")}
    top.connections = [SubenvConnection(**{"from": "adder.dout", "to": "inverter.din"})]
    with pytest.raises(Exception, match="is active and would drive"):
        top.validate_subenv_composition()


def _blk_io(name, agent, iface, dwidth):
    # a block with an output `dout` (8-bit) and an input `din` of `dwidth` bits
    return ProjectConfig(
        project=ProjectMeta(name=name),
        dut=DutConfig(name=name, combinational=True, reset=""),
        agents=[
            AgentConfig(
                name=agent,
                interface=iface,
                sequence_item=f"{agent}_seq_item",
                active=False,
                ports={
                    "inputs": [PortConfig(name="din", width=dwidth)],
                    "outputs": [PortConfig(name="dout", width=8)],
                },
            )
        ],
        tests=[TConf(name=f"{name}_test")],
    )


def test_connection_width_mismatch_rejected():
    from quick_uvm.models import SubenvConnection

    top = _top()
    top.subenv_configs = {
        "adder": _blk_io("adder", "a", "a_if", 8),
        "inverter": _blk_io("inverter", "b", "b_if", 4),  # 4-bit din
    }
    top.connections = [SubenvConnection(**{"from": "adder.dout", "to": "inverter.din"})]
    with pytest.raises(Exception, match="width mismatch"):
        top.validate_subenv_composition()


def test_duplicate_connection_target_rejected():
    from quick_uvm.models import SubenvConnection

    top = _top()
    top.subenv_configs = {
        "adder": _blk_io("adder", "a", "a_if", 8),
        "inverter": _blk_io("inverter", "b", "b_if", 8),
    }
    top.connections = [
        SubenvConnection(**{"from": "adder.dout", "to": "inverter.din"}),
        SubenvConnection(**{"from": "inverter.dout", "to": "inverter.din"}),
    ]
    with pytest.raises(Exception, match="multiple connections drive"):
        top.validate_subenv_composition()


def test_cross_block_scoreboard_unknown_agent_rejected():
    from quick_uvm.models import SubenvScoreboard

    top = _top()
    top.subenv_configs = {
        "adder": _block("adder", "a", "a_if"),
        "inverter": _block("inverter", "b", "b_if"),
    }
    top.subenv_scoreboards = [
        SubenvScoreboard(name="chk", source="adder.a", monitor="inverter.zzz")
    ]
    with pytest.raises(Exception, match="has no agent 'zzz'"):
        top.validate_subenv_composition()


def test_connections_without_subenvs_rejected():
    from quick_uvm.models import SubenvConnection

    with pytest.raises(Exception, match="only valid on a subsystem"):
        ProjectConfig(
            project=ProjectMeta(name="b"),
            dut=DutConfig(name="b", combinational=True, reset=""),
            agents=[
                AgentConfig(
                    name="x",
                    interface="xi",
                    sequence_item="xt",
                    ports={"inputs": [PortConfig(name="din", width=8)]},
                )
            ],
            connections=[SubenvConnection(**{"from": "a.b", "to": "c.d"})],
        )


def test_unknown_param_override_rejected(tmp_path):
    # A subenv overriding a parameter the block does not declare must error.
    top_yaml = tmp_path / "bad.yaml"
    top_yaml.write_text(
        "project: {name: bad}\n"
        "layout: packaged\n"
        "dut: {name: bad, combinational: true, reset: ''}\n"
        "subenvs:\n"
        f"  - {{name: dp, config: {PSOC.parent / 'dp' / 'dp.yaml'}, params: {{Z: 4}}}}\n"
        f"  - {{name: mac, config: {PSOC.parent / 'mac' / 'mac.yaml'}, params: {{W: 16}}}}\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="is not a declared parameter of"):
        ProjectConfig.from_yaml(top_yaml)
