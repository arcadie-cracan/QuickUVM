"""F2' — VIP ownership: generate a versioned, reusable agent VIP, consume an agent from
it BY REFERENCE (wired into the env but not regenerated), and self-test it with no DUT.

The end-to-end behaviour is proven on Xcelium in examples/f2_iovip + f2_con + f2_selftest
(and the M1/M2/M3 mutations in docs/t3_tl_agent_assessment.md §7). These tests pin the
generation LOGIC: what the schema accepts, what a VIP emits, and that a referenced agent is
wired but never regenerated — all without a simulator.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_VIP = {
    "project": {"name": "iovip", "version": "1.0.0"},
    "kind": "vip",
    "layout": "packaged",
    "agents": [
        {
            "name": "io",
            "interface": "io_if",
            "sequence_item": "io_seq_item",
            "ports": {
                "inputs": [{"name": "din", "width": 8}],
                "outputs": [{"name": "dout", "width": 8}],
            },
        }
    ],
}


def _outs(cfg, output_dir=None):
    g = Generator(cfg)
    if output_dir is not None:
        g._output_dir = Path(output_dir)
    return {spec.output for spec in g.files_to_generate()}


def _render(cfg, name, output_dir=None):
    g = Generator(cfg)
    if output_dir is not None:
        g._output_dir = Path(output_dir)
    spec = next(s for s in g.files_to_generate() if s.output == name)
    return g.render(spec)


# --- S1 schema -------------------------------------------------------------


def test_version_defaults_to_something_and_carries():
    assert (
        ProjectConfig.model_validate(
            {
                "project": {"name": "x"},
                "kind": "vip",
                "layout": "packaged",
                "agents": _VIP["agents"],
            }
        ).project.version
        == "0.1.0"
    )
    assert ProjectConfig.model_validate(_VIP).project.version == "1.0.0"


def test_a_vip_needs_no_dut_but_synthesizes_a_nameplate():
    c = ProjectConfig.model_validate(_VIP)
    assert c.is_vip and c.dut.name == "iovip"  # name = project, no RTL emitted


def test_kind_requires_packaged_layout():
    with pytest.raises(ValidationError, match="requires `layout: packaged`"):
        ProjectConfig.model_validate({**_VIP, "layout": "flat"})


def test_vip_forbids_bench_only_features():
    with pytest.raises(ValidationError, match="silently dropped"):
        ProjectConfig.model_validate(
            {
                **_VIP,
                "register_model": {"package": "p", "block": "b", "bus_agent": "io"},
            }
        )


def test_bench_is_byte_identical_default():
    """kind defaults to bench; a normal config is unchanged (no vip/selftest fields)."""
    c = ProjectConfig.model_validate(
        {
            "project": {"name": "d"},
            "dut": {"name": "d", "clock": "clk", "reset": "rst_n"},
            "agents": _VIP["agents"],
        }
    )
    assert c.kind == "bench" and not c.is_vip and not c.is_selftest
    assert c.generated_agents == c.agents  # no refs -> identical


# --- S2 VIP generation -----------------------------------------------------


def test_vip_emits_only_packages_and_manifest():
    outs = _outs(ProjectConfig.model_validate(_VIP))
    # the reusable agent package + its filelist + the manifest
    assert {"io_pkg.sv", "io_pkg.f", "iovip.qvip"} <= outs
    assert {"io_agent.svh", "io_driver.svh", "io_if.sv", "io_seq.svh"} <= outs
    # NOTHING bench-side: no DUT stub, env, scoreboard, test, top, clkgen
    for bench_only in (
        "iovip.sv",
        "iovip_env.svh",
        "iovip_scoreboard.svh",
        "tb_top.sv",
        "iovip_test_pkg.sv",
        "clkgen.sv",
        "run.f",
    ):
        assert bench_only not in outs, bench_only


def test_manifest_records_identity_and_agent_config():
    man = yaml.safe_load(_render(ProjectConfig.model_validate(_VIP), "iovip.qvip"))
    assert man["project"] == "iovip" and man["version"] == "1.0.0"
    io = man["agents"]["io"]
    assert io["package"] == "io_pkg" and io["filelist"] == "io_pkg.f"
    assert io["interface"] == "io_if" and io["sequence_item"] == "io_seq_item"
    # the full config round-trips back into an AgentConfig
    assert io["config"]["name"] == "io"


# --- S3 consume-by-reference ----------------------------------------------


def _make_vip_and_consumer(tmp_path, consumer_extra=None):
    """Generate a VIP to disk, then load a consumer that references it."""
    Generator(ProjectConfig.model_validate(_VIP)).generate_all(
        tmp_path / "iovip" / "gen", backup=False
    )
    (tmp_path / "con").mkdir()
    extra = dict(consumer_extra or {})
    own_agents = extra.pop("agents", [])
    con = {
        "project": {"name": "con"},
        "layout": "packaged",
        "dut": {"name": "con", "clock": "clk", "reset": "", "combinational": True},
        # declared agents first, then the reference entry — one list, two kinds
        "agents": own_agents + [{"name": "io", "from_vip": "../iovip/gen/iovip.qvip"}],
        **extra,
    }
    p = tmp_path / "con" / "con.yaml"
    p.write_text(yaml.safe_dump(con))
    return ProjectConfig.from_yaml(p)


def test_referenced_agent_is_wired_but_flagged(tmp_path):
    cfg = _make_vip_and_consumer(tmp_path)
    io = next(a for a in cfg.agents if a.name == "io")
    assert io.is_reference and io.ref_filelist.endswith("io_pkg.f")
    # wired into the env (in `agents`) but excluded from source generation
    assert io in cfg.agents and cfg.generated_agents == []


def test_referenced_agent_source_is_not_regenerated(tmp_path):
    cfg = _make_vip_and_consumer(tmp_path)
    outs = _outs(cfg, tmp_path / "con" / "gen")
    for src in (
        "io_driver.svh",
        "io_monitor.svh",
        "io_pkg.sv",
        "io_if.sv",
        "io_seq.svh",
    ):
        assert src not in outs, f"referenced agent must not regenerate {src}"
    # but the env still exists and wires it
    assert "con_env.svh" in outs


def test_env_imports_and_chains_the_referenced_vip(tmp_path):
    cfg = _make_vip_and_consumer(tmp_path)
    out = tmp_path / "con" / "gen"
    env_pkg = _render(cfg, "con_env_pkg.sv", out)
    assert "import io_pkg::*;" in env_pkg
    env_f = _render(cfg, "con_env_pkg.f", out)
    # chained with -F (capital: paths relative to the file), not -f, at the right relpath
    assert "-F ../../iovip/gen/io_pkg.f" in env_f
    assert "-f io_pkg.f" not in env_f
    env = _render(cfg, "con_env.svh", out)
    assert (
        "io_agent" in env and "io_agnt" in env
    )  # the class comes from the imported pkg


def test_missing_manifest_is_a_clear_error(tmp_path):
    (tmp_path / "con").mkdir()
    p = tmp_path / "con" / "con.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "con"},
                "layout": "packaged",
                "dut": {
                    "name": "con",
                    "clock": "clk",
                    "reset": "",
                    "combinational": True,
                },
                "agents": [{"name": "io", "from_vip": "../nope/gen/nope.qvip"}],
            }
        )
    )
    with pytest.raises(Exception, match="manifest not found"):
        ProjectConfig.from_yaml(p)


def test_by_reference_requires_packaged(tmp_path):
    # raised by the from_yaml loader (which is where refs are resolved)
    with pytest.raises(Exception, match="requires.*packaged"):
        _make_vip_and_consumer(tmp_path, {"layout": "flat"})


# --- S4 self-test ----------------------------------------------------------


def test_selftest_emits_loopback_top_and_no_dut(tmp_path):
    Generator(ProjectConfig.model_validate(_VIP)).generate_all(
        tmp_path / "iovip" / "gen", backup=False
    )
    (tmp_path / "st").mkdir()
    p = tmp_path / "st" / "st.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "st"},
                "kind": "selftest",
                "layout": "packaged",
                "clock": {"period": 10, "unit": "ns"},
                "agents": [{"name": "io", "from_vip": "../iovip/gen/iovip.qvip"}],
            }
        )
    )
    cfg = ProjectConfig.from_yaml(p)
    assert cfg.is_selftest
    outs = _outs(cfg, tmp_path / "st" / "gen")
    assert "tb_top.sv" in outs and "st.sv" not in outs  # a top, but no DUT stub
    top = _render(cfg, "tb_top.sv", tmp_path / "st" / "gen")
    assert "selftest_loopback" in top and "dut_inst" not in top
    # run.f omits the (absent) DUT stub
    assert "st.sv" not in _render(cfg, "run.f", tmp_path / "st" / "gen")


# --- robustness + the own-agent-AND-ref topology (adversarial-review findings) --------


def test_consumer_with_own_agent_and_a_ref(tmp_path):
    """The mainline reuse topology: a bench with its OWN agent PLUS a referenced VIP agent.
    Both are wired; the own agent is generated, the referenced one is not; the env filelist
    chains the own package with -f and the VIP with -F."""
    cfg = _make_vip_and_consumer(
        tmp_path,
        {
            "agents": [
                {
                    "name": "own",
                    "interface": "own_if",
                    "sequence_item": "own_seq_item",
                    "ports": {
                        "inputs": [{"name": "a", "width": 4}],
                        "outputs": [{"name": "b", "width": 4}],
                    },
                }
            ],
        },
    )
    names = {a.name for a in cfg.agents}
    assert names == {"own", "io"}
    assert [a.name for a in cfg.generated_agents] == [
        "own"
    ]  # io referenced, own generated
    out = tmp_path / "con" / "gen"
    outs = _outs(cfg, out)
    assert "own_driver.svh" in outs and "io_driver.svh" not in outs
    env_f = _render(cfg, "con_env_pkg.f", out)
    assert "-f own_pkg.f" in env_f and "-F ../../iovip/gen/io_pkg.f" in env_f


def test_ref_name_is_authoritative_over_a_corrupt_manifest_key(tmp_path):
    """A hand-edited manifest whose config.name != the key must still wire under the ref
    name the consumer uses (not silently under the wrong name)."""
    Generator(ProjectConfig.model_validate(_VIP)).generate_all(
        tmp_path / "iovip" / "gen", backup=False
    )
    man = tmp_path / "iovip" / "gen" / "iovip.qvip"
    data = yaml.safe_load(man.read_text())
    data["agents"]["io"]["config"]["name"] = "WRONG"  # corrupt: config.name != key
    man.write_text(yaml.safe_dump(data))
    (tmp_path / "con").mkdir()
    p = tmp_path / "con" / "con.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "con"},
                "layout": "packaged",
                "dut": {
                    "name": "con",
                    "clock": "clk",
                    "reset": "",
                    "combinational": True,
                },
                "agents": [{"name": "io", "from_vip": "../iovip/gen/iovip.qvip"}],
            }
        )
    )
    cfg = ProjectConfig.from_yaml(p)
    assert [a.name for a in cfg.agents] == ["io"]  # the ref name wins, not "WRONG"


def test_corrupt_manifest_missing_filelist_is_a_clear_error(tmp_path):
    Generator(ProjectConfig.model_validate(_VIP)).generate_all(
        tmp_path / "iovip" / "gen", backup=False
    )
    man = tmp_path / "iovip" / "gen" / "iovip.qvip"
    data = yaml.safe_load(man.read_text())
    del data["agents"]["io"]["filelist"]
    man.write_text(yaml.safe_dump(data))
    (tmp_path / "con").mkdir()
    p = tmp_path / "con" / "con.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "con"},
                "layout": "packaged",
                "dut": {
                    "name": "con",
                    "clock": "clk",
                    "reset": "",
                    "combinational": True,
                },
                "agents": [{"name": "io", "from_vip": "../iovip/gen/iovip.qvip"}],
            }
        )
    )
    with pytest.raises(Exception, match="no `filelist`"):
        ProjectConfig.from_yaml(p)


def test_unresolved_from_vip_entry_fails_loudly():
    """`from_vip` entries are resolved by from_yaml; a bare model_validate cannot
    do the file I/O, and silently generating nothing for them would be a footgun —
    reject with the from_yaml hint."""
    with pytest.raises(ValidationError, match="from_yaml"):
        ProjectConfig.model_validate(
            {
                "project": {"name": "con"},
                "layout": "packaged",
                "dut": {"name": "con", "clock": "clk", "reset": ""},
                "agents": [{"name": "other", "from_vip": "x.qvip"}],
            }
        )


def test_old_agent_refs_key_errors_with_move_hint():
    with pytest.raises(ValidationError, match="moved INTO `agents:`"):
        ProjectConfig.model_validate(
            {
                "project": {"name": "con"},
                "layout": "packaged",
                "dut": {"name": "con", "clock": "clk", "reset": ""},
                "agents": _VIP["agents"],
                "agent_refs": [{"name": "io", "manifest": "x.qvip"}],
            }
        )
