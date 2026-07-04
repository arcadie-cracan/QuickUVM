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


def test_subenvs_reject_own_agents():
    with pytest.raises(Exception, match="must not define its own `agents`"):
        ProjectConfig(
            project=ProjectMeta(name="soc"),
            dut=DutConfig(name="soc", combinational=True, reset=""),
            layout="packaged",
            agents=[
                AgentConfig(
                    name="x",
                    interface="xi",
                    sequence_item="xt",
                    ports={"inputs": [PortConfig(name="din", width=8)]},
                )
            ],
            subenvs=[
                __import__("quick_uvm.models", fromlist=["SubenvConfig"]).SubenvConfig(
                    name="a", config="a.yaml"
                ),
                __import__("quick_uvm.models", fromlist=["SubenvConfig"]).SubenvConfig(
                    name="b", config="b.yaml"
                ),
            ],
            tests=[TConf(name="t")],
        )


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


def test_clocked_child_block_rejected():
    top = _top()
    clocked = ProjectConfig(
        project=ProjectMeta(name="clkblk"),
        dut=DutConfig(name="clkblk", combinational=False, reset="rst_n"),
        agents=[
            AgentConfig(
                name="c",
                interface="c_if",
                sequence_item="c_seq_item",
                ports={"inputs": [PortConfig(name="din", width=8)]},
            )
        ],
        tests=[TConf(name="c_test")],
    )
    top.subenv_configs = {"adder": _block("adder", "a", "a_if"), "inverter": clocked}
    with pytest.raises(Exception, match="only combinational child blocks"):
        top.validate_subenv_composition()


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


def test_top_with_analysis_rejected():
    from quick_uvm.models import AnalysisConfig

    with pytest.raises(Exception, match="must not set analysis"):
        _top(analysis=AnalysisConfig())


def test_generate_without_loaded_children_errors():
    # A top constructed in-memory (not via from_yaml) has no loaded children.
    with pytest.raises(Exception, match="child configs are not loaded"):
        Generator(_top()).files_to_generate()


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


def test_namespaced_block_rejects_connection(tmp_path):
    # A namespaced (reused) block may not be referenced by a cross-block wire yet.
    from quick_uvm.models import ProjectConfig as PC

    cfg = _mkblock(tmp_path)
    top = tmp_path / "top.yaml"
    top.write_text(
        "project: {name: top}\n"
        "layout: packaged\n"
        "dut: {name: top, combinational: true, reset: ''}\n"
        "subenvs:\n"
        f"  - {{name: lo, config: {cfg}, params: {{W: 8}}}}\n"
        f"  - {{name: hi, config: {cfg}, params: {{W: 16}}}}\n"
        "connections: [{from: lo.dout, to: hi.din}]\n"
        "tests: [{name: t}]\n"
    )
    with pytest.raises(Exception, match="is namespaced"):
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
    with pytest.raises(Exception, match="is not a declared parameter of block"):
        ProjectConfig.from_yaml(top_yaml)
