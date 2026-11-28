"""`resolve` — the effective topology with provenance (issue #116).

The config understates the artifact: an implicit scoreboard and coverage collector on
the primary agent, the auto virtual sequence, the default `test1` and each agent's
`<agent>_seq` can all appear in a bench without appearing in the YAML. Until now the
only way to learn what a config MEANT was to generate it and read the SystemVerilog.

`manifest` cannot answer it — it is byte-identical with and without an `analysis:`
block, because it maps files to owners rather than describing topology. That property
is asserted here, because it is the reason this command exists.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_AGENT = {
    "name": "pkt",
    "interface": "pkt_if",
    "sequence_item": "pkt_item",
    "ports": {
        "inputs": [{"name": "in_valid", "width": 1}],
        "outputs": [{"name": "out_valid", "width": 1}],
    },
}
_SB = {"name": "sbd", "source": "pkt"}


def _cfg(**over):
    data = {
        "project": {"name": "y"},
        "dut": {"name": "y", "clock": "clk", "reset": "rst_n"},
        "agents": [_AGENT],
        **over,
    }
    return ProjectConfig.model_validate(data)


# --- provenance ------------------------------------------------------------------


def test_implicit_components_are_marked_inferred():
    """The whole point: these appear NOWHERE in the YAML."""
    r = _cfg().resolved()
    assert r["analysis"]["mode"] == "implicit"
    assert r["analysis"]["scoreboards"] == [
        {"name": "sbd", "source": "pkt", "origin": "inferred"}
    ]
    assert r["analysis"]["coverage"] == [{"agent": "pkt", "origin": "inferred"}]


def test_declared_components_are_marked_declared():
    r = _cfg(analysis={"coverage": ["pkt"], "scoreboards": [_SB]}).resolved()
    assert r["analysis"]["mode"] == "declared"
    assert r["analysis"]["scoreboards"][0]["origin"] == "declared"
    assert r["analysis"]["coverage"] == [{"agent": "pkt", "origin": "declared"}]


def test_the_mode_switch_is_visible_as_a_disappearance():
    """The reported confusion, in one assertion: declaring a scoreboard removes the
    coverage entry entirely — which is exactly what the diagram could not show."""
    before = _cfg().resolved()["analysis"]
    after = _cfg(analysis={"scoreboards": [_SB]}).resolved()["analysis"]
    assert before["coverage"] == [{"agent": "pkt", "origin": "inferred"}]
    assert after["coverage"] == []


def test_the_default_sequence_every_agent_never_asked_for():
    r = _cfg().resolved()
    assert r["agents"][0]["sequences"] == [{"name": "pkt_seq", "origin": "inferred"}]


def test_declared_sequences_keep_their_provenance():
    agent = {**_AGENT, "sequences": [{"name": "burst", "kind": "random"}]}
    r = _cfg(agents=[agent]).resolved()
    names = {s["name"]: s["origin"] for s in r["agents"][0]["sequences"]}
    assert names == {"pkt_seq": "inferred", "burst": "declared"}


def test_default_test_is_inferred_and_a_declared_one_is_not():
    assert _cfg().resolved()["tests"] == [{"name": "test1", "origin": "inferred"}]
    r = _cfg(tests=[{"name": "rand_test", "num_items": 5}]).resolved()
    assert r["tests"] == [{"name": "rand_test", "origin": "declared"}]


# --- guards ----------------------------------------------------------------------


def test_guards_report_what_the_run_will_complain_about():
    """Answering "will it warn, and why" without running a simulation."""
    assert _cfg().resolved()["guards"] == []
    assert _cfg(analysis={"scoreboards": [_SB]}).resolved()["guards"] == [
        "UNCOVERED_AGENT: pkt"
    ]


# --- why this is not `manifest` --------------------------------------------------


def test_manifest_cannot_answer_this():
    """The justification for a separate command, pinned as a test: the manifest is
    IDENTICAL either side of the mode switch, while the topology is not."""
    implicit = Generator(_cfg()).manifest()
    declared = Generator(_cfg(analysis={"scoreboards": [_SB]})).manifest()
    assert implicit == declared
    assert (
        _cfg().resolved()["analysis"]
        != _cfg(analysis={"scoreboards": [_SB]}).resolved()["analysis"]
    )


# --- the CLI ---------------------------------------------------------------------


def test_cli_emits_valid_json(tmp_path):
    cfg = tmp_path / "y.yaml"
    cfg.write_text(
        "project: {name: y}\n"
        "dut: {name: y, clock: clk, reset: rst_n}\n"
        "agents:\n"
        "  - name: pkt\n"
        "    interface: pkt_if\n"
        "    sequence_item: pkt_item\n"
        "    ports:\n"
        "      inputs:  [{name: in_valid, width: 1}]\n"
        "      outputs: [{name: out_valid, width: 1}]\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            "from quick_uvm.cli import main; main()",
            "resolve",
            "-c",
            str(cfg),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["analysis"]["mode"] == "implicit"
    assert out["dut"] == "y"


def test_cli_writes_to_a_file(tmp_path):
    cfg = tmp_path / "y.yaml"
    cfg.write_text(
        "project: {name: y}\n"
        "dut: {name: y, clock: clk, reset: rst_n}\n"
        "agents:\n"
        "  - name: pkt\n"
        "    interface: pkt_if\n"
        "    sequence_item: pkt_item\n"
        "    ports:\n"
        "      inputs:  [{name: in_valid, width: 1}]\n"
        "      outputs: [{name: out_valid, width: 1}]\n",
        encoding="utf-8",
    )
    dest = tmp_path / "resolved.json"
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            "from quick_uvm.cli import main; main()",
            "resolve",
            "-c",
            str(cfg),
            "-o",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(dest.read_text(encoding="utf-8"))["dut"] == "y"


# --- read-only -------------------------------------------------------------------


def test_resolve_generates_nothing(tmp_path):
    """It must not write a testbench as a side effect."""
    cfg = tmp_path / "y.yaml"
    cfg.write_text(
        "project: {name: y}\n"
        "dut: {name: y, clock: clk, reset: rst_n}\n"
        "agents:\n"
        "  - name: pkt\n"
        "    interface: pkt_if\n"
        "    sequence_item: pkt_item\n"
        "    ports:\n"
        "      inputs:  [{name: in_valid, width: 1}]\n"
        "      outputs: [{name: out_valid, width: 1}]\n",
        encoding="utf-8",
    )
    before = set(p.name for p in tmp_path.iterdir())
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from quick_uvm.cli import main; main()",
            "resolve",
            "-c",
            str(cfg),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert set(p.name for p in tmp_path.iterdir()) == before


# --- the report agrees with the generated env (#121) ------------------------------
#
# `resolved()` mirrors the templates, and it drifted: it reported the implicit pair
# on three shapes whose env never renders it, the flat bench's guards on a
# composition, a test and a virtual sequence on a VIP that emits neither. So each
# shape is checked against what the generator WRITES, in both directions -- the
# report is right only if the two agree.

_EX = Path(__file__).resolve().parents[1] / "examples"
_SBD = re.compile(r"_scoreboard\s+sbd\s*;")
# the collector's declaration, parameterized or not: `pkt_cov cov;`, `pkt_cov #(8) cov;`
_COV = re.compile(r"_cov\b[^;\n]*\bcov\s*;")
# every member the env DECLARES of a scoreboard / collector type -> its handle
_SB_DECL = re.compile(r"^[ \t]*\w+_scoreboard\b[^;\n=:]*?\b(\w+)[ \t]*;", re.M)
_COV_DECL = re.compile(r"^[ \t]*\w+_cov\b[^;\n=:]*?\b(\w+)[ \t]*;", re.M)
_REPLICAS = {**_AGENT, "replicas": 3}
_SECOND = {
    "name": "rsp",
    "interface": "rsp_if",
    "sequence_item": "rsp_item",
    "ports": {
        "inputs": [{"name": "rsp_ready", "width": 1}],
        "outputs": [{"name": "rsp_valid", "width": 1}],
    },
}

_HYBRID_TOP = """\
project: {name: sys_top}
layout: packaged
dut: {name: sys_top, clock: clk, reset: "", combinational: true}
subenvs:
  - {name: p1, config: producer.yaml}
  - {name: c1, config: consumer.yaml}
connections:
  - {from: p1.dout, to: c1.din}
agents:
  - name: topcmd
    interface: topcmd_if
    sequence_item: topcmd_item
    ports:
      inputs: [{name: z, width: 8}]
      outputs: [{name: zq, width: 8, randomize: false}]
"""
_PURE_TOP = _HYBRID_TOP.split("agents:")[0]


def _block(module, agent, din, dout, active=True):
    return (
        f"project: {{name: {module}}}\n"
        f'dut: {{name: {module}, clock: clk, reset: "", combinational: true}}\n'
        "agents:\n"
        f"  - name: {agent}\n"
        f"    interface: {agent}_if\n"
        f"    sequence_item: {agent}_item\n"
        + ("" if active else "    active: false\n")
        + "    ports:\n"
        f"      inputs: [{{name: {din}, width: 8}}]\n"
        f"      outputs: [{{name: {dout}, width: 8, randomize: false}}]\n"
    )


def _composition(tmp_path, top=_HYBRID_TOP, extra=""):
    (tmp_path / "top.yaml").write_text(top + extra, encoding="utf-8")
    (tmp_path / "producer.yaml").write_text(
        _block("producer", "prod_agent", "pin", "dout"), encoding="utf-8"
    )
    (tmp_path / "consumer.yaml").write_text(
        _block("consumer", "cons_agent", "din", "cout", active=False),
        encoding="utf-8",
    )
    return ProjectConfig.from_yaml(tmp_path / "top.yaml")


def _env_of(cfg, out):
    """The generated env's text, or None when the bench has no env file."""
    Generator(cfg).generate_all(out)
    hits = list(out.rglob(f"{cfg.dut.name}_env.svh"))
    return hits[0].read_text(encoding="utf-8") if hits else None


def _tree(cfg, out):
    """Every generated file's text, by relative path."""
    Generator(cfg).generate_all(out)
    return {
        p.relative_to(out).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }


def _inferred(cfg):
    a = cfg.resolved()["analysis"]
    return (
        [s["name"] for s in a["scoreboards"] if s["origin"] == "inferred"],
        [c["agent"] for c in a["coverage"] if c["origin"] == "inferred"],
    )


def _declared_by(env):
    """(scoreboard handles, collector handles) the env declares as members."""
    env = env or ""
    return set(_SB_DECL.findall(env)), set(_COV_DECL.findall(env))


def _reported_by(r):
    """The same two sets, as `resolved()` reports them: the analysis entries that
    are rendered, plus the per-instance scoreboards. A collector's handle is `cov`
    when inferred and `<agent>_cov_h` when declared (env.svh.j2)."""
    sbs = {s["name"] for s in r["analysis"]["scoreboards"] if s.get("wired", True)}
    sbs |= {i["scoreboard"]["name"] for i in r.get("instances", [])}
    cov = {
        "cov" if c["origin"] == "inferred" else f"{c['agent']}_cov_h"
        for c in r["analysis"]["coverage"]
        if c.get("wired", True)
    }
    return sbs, cov


def test_the_handle_patterns_read_an_env():
    """The two patterns the comparisons below stand on, on the lines they must and
    must not take -- a pattern that matched nothing would make every one vacuous."""
    env = (
        "  y_scoreboard sbd;\n"
        "  nchan_ch_0_scoreboard  ch_0_sb;\n"
        "  pkt_cov #(8) cov;\n"
        "  pkt_cov pkt_cov_h;\n"
        '    sbd = y_scoreboard::type_id::create("sbd", this);\n'
        '    pkt_cov_h = pkt_cov::type_id::create("pkt_cov_h", this);\n'
        "  y_scoreboard_cfg sb_cfg;\n"
        "    pkt_agnt.ap.connect(cov.analysis_export);\n"
    )
    assert _declared_by(env) == ({"sbd", "ch_0_sb"}, {"cov", "pkt_cov_h"})
    assert _COV.search("  pkt_cov #(8) cov;") and _COV.search("  pkt_cov cov;")
    assert not _COV.search("  pkt_cov pkt_cov_h;")


def test_the_plain_bench_renders_the_pair_it_reports(tmp_path):
    """The control: here the report was always right."""
    cfg = _cfg()
    assert cfg.implicit_pair_shape and cfg.implicit_analysis_wired
    assert _inferred(cfg) == (["sbd"], ["pkt"])
    env = _env_of(cfg, tmp_path)
    assert _SBD.search(env) and _COV.search(env)
    assert _declared_by(env) == _reported_by(cfg.resolved()) == ({"sbd"}, {"cov"})
    assert "instances" not in cfg.resolved(), "no new key on a bench without instances"


def test_a_declared_analysis_is_rendered_as_reported(tmp_path):
    """Declared mode on a plain bench: the env declares what the YAML lists, and
    the entries carry no `wired` key -- that answer did not change."""
    cfg = _cfg(analysis={"coverage": ["pkt"], "scoreboards": [_SB]})
    assert cfg.implicit_pair_shape and not cfg.implicit_analysis_wired
    r = cfg.resolved()
    assert r["analysis"]["scoreboards"] == [
        {"name": "sbd", "source": "pkt", "origin": "declared"}
    ]
    env = _env_of(cfg, tmp_path)
    assert _declared_by(env) == _reported_by(r) == ({"sbd"}, {"pkt_cov_h"})


def test_a_selftest_renders_the_pair_it_reports(tmp_path):
    """NOT one of the three shapes: a selftest has an env, and the env has the pair."""
    cfg = _cfg(kind="selftest", layout="packaged")
    assert cfg.implicit_analysis_wired
    assert _inferred(cfg) == (["sbd"], ["pkt"])
    env = _env_of(cfg, tmp_path)
    assert _SBD.search(env) and _COV.search(env)
    assert _declared_by(env) == _reported_by(cfg.resolved())


def test_replicas_report_no_implicit_pair_and_the_env_has_none(tmp_path):
    cfg = _cfg(agents=[_REPLICAS])
    assert not cfg.implicit_pair_shape and not cfg.implicit_analysis_wired
    assert _inferred(cfg) == ([], [])
    assert cfg.resolved()["analysis"]["mode"] == "implicit", (
        "the MODE is still implicit"
    )
    env = _env_of(cfg, tmp_path)
    assert not _SBD.search(env) and not _COV.search(env)


def test_replicas_report_their_per_instance_scoreboards(tmp_path):
    """What IS there, and was never reported: one scoreboard per replica."""
    cfg = _cfg(agents=[_REPLICAS])
    inst = cfg.resolved()["instances"]
    assert inst == [
        {
            "name": f"pkt_{i}",
            "agent": "pkt",
            "origin": "inferred",
            "scoreboard": {
                "name": f"pkt_{i}_sb",
                "origin": "inferred",
                "owner": f"scoreboard:pkt_{i}",
            },
        }
        for i in range(3)
    ]
    env = _env_of(cfg, tmp_path)
    for i in inst:
        assert re.search(
            rf"_{i['name']}_scoreboard\s+{i['scoreboard']['name']}\s*;", env
        ), f"the env does not declare {i['scoreboard']['name']}"
    # ... and the env declares no scoreboard the report does not name
    assert _declared_by(env) == _reported_by(cfg.resolved())
    assert _declared_by(env)[0] == {f"pkt_{i}_sb" for i in range(3)}


def test_an_instance_scoreboards_owner_is_the_manifests(tmp_path):
    """`owner` joins the report to `manifest`: the element that owns the
    scoreboard's files is named after the INSTANCE (`scoreboard:pkt_0`), which is
    neither the handle (`pkt_0_sb`) nor an `analysis.scoreboards` name."""
    for cfg in (
        _cfg(agents=[_REPLICAS]),
        ProjectConfig.from_yaml(_EX / "twowidth" / "twowidth.yaml"),
    ):
        owned = {
            e["owner"]: [f["file"] for f in e["files"]]
            for e in Generator(cfg).manifest()["elements"]
        }
        inst = cfg.resolved()["instances"]
        assert inst
        for i in inst:
            owner = i["scoreboard"]["owner"]
            assert owner == f"scoreboard:{i['name']}"
            assert any(f.endswith("_scoreboard.svh") for f in owned[owner]), (
                f"the manifest has no scoreboard file under {owner}"
            )
        # every scoreboard element of the manifest is one the report names
        assert {o for o in owned if o.startswith("scoreboard:")} == {
            i["scoreboard"]["owner"] for i in inst
        }


def test_a_scoreboard_declared_on_replicas_is_reported_as_not_wired(tmp_path):
    """The only analysis entries a `replicas` bench accepts -- plain single-stream
    scoreboards -- render no component: on the default flat layout the bench is the
    same with one, with two, with one renamed, and without any. The report says so
    (`wired: false`) instead of presenting components the env does not hold."""
    bare = _cfg(agents=[_REPLICAS])
    with_sb = _cfg(agents=[_REPLICAS], analysis={"scoreboards": [_SB]})
    other = {"name": "other", "source": "pkt"}
    renamed = _cfg(agents=[_REPLICAS], analysis={"scoreboards": [other]})
    two = _cfg(agents=[_REPLICAS], analysis={"scoreboards": [_SB, other]})
    assert bare.layout == "flat"
    r = with_sb.resolved()
    assert r["analysis"] == {
        "mode": "declared",
        "scoreboards": [
            {"name": "sbd", "source": "pkt", "origin": "declared", "wired": False}
        ],
        "coverage": [],
    }
    assert r["instances"] == bare.resolved()["instances"]
    base = _tree(bare, tmp_path / "bare")
    assert _tree(with_sb, tmp_path / "with") == base, (
        "a declared scoreboard changed a replicas bench: `wired: false` is no longer true"
    )
    assert _tree(renamed, tmp_path / "renamed") == base
    assert _tree(two, tmp_path / "two") == base
    assert [s["wired"] for s in two.resolved()["analysis"]["scoreboards"]] == [
        False,
        False,
    ]
    env = next(v for k, v in base.items() if k.endswith("y_env.svh"))
    assert _declared_by(env) == _reported_by(r)
    assert "sbd" not in _declared_by(env)[0]


def test_a_virtual_sequence_declared_on_a_composition_is_not_wired(tmp_path):
    """Accepted, and rendered nowhere: the composition's templates are handed no
    declared virtual sequence, only `<top>_vseq` exists. Reported -- it is in the
    YAML -- and marked."""
    cfg = _composition(
        tmp_path,
        extra="virtual_sequences:\n"
        "  - name: myvs\n"
        "    body: [{agent: topcmd, sequence: topcmd_seq}]\n",
    )
    assert cfg.resolved()["virtual_sequences"] == [
        {"name": "myvs", "origin": "declared", "wired": False},
        {"name": "sys_top_vseq", "origin": "inferred"},
    ]
    files = _tree(cfg, tmp_path / "g")
    assert not [f for f, t in files.items() if "myvs" in f or "myvs" in t], (
        "a declared vseq is rendered on a composition now: `wired: false` is no "
        "longer true"
    )
    # the control: on a flat bench the same declaration IS a class, and unmarked
    flat = _cfg(
        agents=[_AGENT, _SECOND],
        virtual_sequences=[
            {"name": "myvs", "body": [{"agent": "pkt", "sequence": "pkt_seq"}]}
        ],
    )
    assert flat.resolved()["virtual_sequences"] == [
        {"name": "myvs", "origin": "declared"}
    ]
    assert any("myvs" in t for t in _tree(flat, tmp_path / "flat").values())


def test_a_coverage_entry_on_a_vip_is_not_wired(tmp_path):
    """A VIP takes a RICH coverage entry: its covergroup goes into the agent
    package's `<agent>_cov.svh`. There is no env, so no collector component --
    reported, since it shapes a shipped file, and marked."""
    rich = {"agent": "pkt", "coverpoints": [{"field": "in_valid"}]}
    cfg = _cfg(kind="vip", layout="packaged", analysis={"coverage": [rich]})
    assert cfg.resolved()["analysis"] == {
        "mode": "declared",
        "scoreboards": [],
        "coverage": [{"agent": "pkt", "origin": "declared", "wired": False}],
    }
    files = _tree(cfg, tmp_path / "vip")
    assert not [f for f in files if f.endswith("_env.svh")]
    assert _reported_by(cfg.resolved()) == (set(), set())
    # it is not inert: the entry changes the collector class the package ships
    plain = _tree(_cfg(kind="vip", layout="packaged"), tmp_path / "plain")
    changed = [f for f in files if files[f] != plain.get(f)]
    assert [f.rsplit("/", 1)[-1] for f in changed] == ["pkt_cov.svh"]


def test_replicas_did_not_lose_a_collector_they_never_had(tmp_path):
    """UNCOVERED_AGENT says "you traded your collector for this scoreboard". A
    `replicas` bench has no collector to trade (and cannot ask for one), so the
    guard is neither reported nor rendered there -- it used to be both."""
    cfg = _cfg(agents=[_REPLICAS], analysis={"scoreboards": [_SB]})
    assert cfg.uncovered_agents == []
    assert cfg.resolved()["guards"] == []
    assert "UNCOVERED_AGENT" not in _env_of(cfg, tmp_path / "r")
    # the control: on a plain bench the same analysis block DID cost a collector
    plain = _cfg(analysis={"scoreboards": [_SB]})
    assert plain.resolved()["guards"] == ["UNCOVERED_AGENT: pkt"]
    assert "UNCOVERED_AGENT" in _env_of(plain, tmp_path / "p")


def test_instances_are_declared_their_scoreboards_inferred(tmp_path):
    """C3 `instances`: the user named the instances, nobody declared the scoreboards."""
    cfg = ProjectConfig.from_yaml(_EX / "twowidth" / "twowidth.yaml")
    assert not cfg.implicit_analysis_wired
    assert _inferred(cfg) == ([], [])
    inst = cfg.resolved()["instances"]
    assert [(i["name"], i["origin"]) for i in inst] == [
        ("io8", "declared"),
        ("io16", "declared"),
    ]
    assert all(i["scoreboard"]["origin"] == "inferred" for i in inst)
    env = _env_of(cfg, tmp_path)
    assert not _SBD.search(env) and not _COV.search(env)
    assert _declared_by(env) == _reported_by(cfg.resolved())
    assert _declared_by(env)[0] == {i["scoreboard"]["name"] for i in inst}


def test_a_vip_reports_only_what_its_packages_hold(tmp_path):
    """`kind: vip` emits agent packages and a manifest. Two stimulus agents, so the
    old report also named an auto virtual sequence, the default test and an
    UNCHECKED_AGENT guard -- for a tree with no vseq, no test and no env."""
    cfg = _cfg(kind="vip", layout="packaged", agents=[_AGENT, _SECOND])
    assert cfg.auto_vseq_name is not None and cfg.unchecked_stimulus_agents, (
        "the fixture no longer exercises the flat rules the VIP must not report"
    )
    assert not cfg.implicit_pair_shape
    r = cfg.resolved()
    assert r["analysis"] == {"mode": "implicit", "scoreboards": [], "coverage": []}
    assert (r["tests"], r["virtual_sequences"], r["guards"]) == ([], [], [])
    assert "instances" not in r
    files = _tree(cfg, tmp_path)
    assert not [f for f in files if f.endswith("_env.svh")]
    assert not [f for f in files if "vseq" in f or "test1" in f or "base_test" in f]
    # ... and no generated file mentions the scoreboard the old report named
    assert not [f for f, t in files.items() if re.search(r"\bsbd\b", t)]
    # what a VIP does ship is still reported: each agent's default sequence
    for a in r["agents"]:
        seq = a["sequences"][0]
        assert seq["origin"] == "inferred"
        assert any(f.endswith(f"{seq['name']}.svh") for f in files), seq["name"]


def test_a_vip_with_replicas_reports_no_instances(tmp_path):
    """Per-instance scoreboards live in an env; a VIP has none."""
    cfg = _cfg(kind="vip", layout="packaged", agents=[_REPLICAS])
    assert cfg.instance_views, "the fixture no longer has instance views"
    assert "instances" not in cfg.resolved()
    assert not [f for f in _tree(cfg, tmp_path) if "scoreboard" in f]


def test_a_composition_with_a_boundary_agent_reports_no_implicit_pair(tmp_path):
    """The hybrid: `agents[0]` exists, so the old report inferred a pair on it; the
    subsystem's env wires the blocks' envs and has no implicit branch."""
    cfg = _composition(tmp_path)
    assert not cfg.implicit_pair_shape and not cfg.implicit_analysis_wired
    assert _inferred(cfg) == ([], [])
    env = _env_of(cfg, tmp_path / "g")
    assert env is not None
    assert not _SBD.search(env) and "topcmd_cov" not in env
    assert _declared_by(env) == _reported_by(cfg.resolved()) == (set(), set())


def test_a_compositions_guards_are_the_compositions(tmp_path):
    """The top vseq drives every active boundary agent and nothing is wired by
    default, so ONE boundary agent is already driven-and-unchecked. The flat rule
    (two stimulus agents, the primary excused) said nothing here -- about a bench
    that warns at every run."""
    cfg = _composition(tmp_path)
    assert cfg.unchecked_stimulus_agents == [], "the flat rule has nothing to say"
    assert cfg.unchecked_boundary_agents == ["topcmd"]
    assert cfg.resolved()["guards"] == ["UNCHECKED_AGENT: topcmd"]
    env = _env_of(cfg, tmp_path / "g")
    assert re.search(r"UNCHECKED_AGENT[^;]*boundary agent 'topcmd'", env)
    # the advice names the key that exists (`subenv_scoreboards:` is rejected)
    assert "`analysis.scoreboards`" in env and "subenv_scoreboards:" not in env


def test_a_bare_endpoint_checks_the_boundary_agent_a_dotted_one_does_not(tmp_path):
    for name, sb, guards in (
        ("bare", "{name: e2e, source: topcmd, monitor: c1.cons_agent}", []),
        (
            "dotted",
            "{name: e2e, source: p1.prod_agent, monitor: c1.cons_agent}",
            ["UNCHECKED_AGENT: topcmd"],
        ),
    ):
        d = tmp_path / name
        d.mkdir()
        cfg = _composition(d, extra=f"analysis:\n  scoreboards:\n    - {sb}\n")
        r = cfg.resolved()
        assert r["guards"] == guards, name
        env = _env_of(cfg, d / "g")
        assert ("UNCHECKED_AGENT" in env) == bool(guards), name
        # the cross-block scoreboard is declared by the env under the name reported
        assert _declared_by(env) == _reported_by(r) == ({"e2e"}, set()), name


def test_a_passive_boundary_agent_is_not_driven_so_not_unchecked(tmp_path):
    cfg = _composition(
        tmp_path, top=_HYBRID_TOP.replace("    ports:", "    active: false\n    ports:")
    )
    assert not cfg.agents[0].active
    assert cfg.resolved()["guards"] == []
    assert "UNCHECKED_AGENT" not in _env_of(cfg, tmp_path / "g")


def test_a_composition_always_has_its_top_virtual_sequence(tmp_path):
    """Generated at every composition level, with or without boundary agents --
    the flat rule (two stimulus agents) reported none."""
    for name, top in (("hybrid", _HYBRID_TOP), ("pure", _PURE_TOP)):
        d = tmp_path / name
        d.mkdir()
        cfg = _composition(d, top=top)
        assert cfg.auto_vseq_name is None, "the flat rule has nothing to say"
        assert cfg.resolved()["virtual_sequences"] == [
            {"name": "sys_top_vseq", "origin": "inferred"}
        ]
        assert any(f.endswith("sys_top_vseq.svh") for f in _tree(cfg, d / "g")), name
        if name == "pure":
            assert cfg.resolved()["guards"] == []


def test_what_was_reported_could_not_be_declared(tmp_path):
    """Why the over-report was not harmless: the reported pair, written into
    `analysis:`, is REFUSED on each of these shapes -- so a consumer that kept it
    turned a bench that generates into one that does not. (On `replicas` it is the
    collector that is refused; the scoreboard alone is accepted and renders
    nothing -- test_a_scoreboard_declared_on_replicas_is_reported_as_not_wired.)"""
    pair = {"scoreboards": [_SB], "coverage": ["pkt"]}
    with pytest.raises(ValueError, match="does not yet wire coverage"):
        _cfg(agents=[_REPLICAS], analysis=pair)
    with pytest.raises(ValueError, match="silently dropped"):
        _cfg(kind="vip", layout="packaged", analysis=pair)
    with pytest.raises(ValueError, match="does not wire `analysis.coverage`"):
        _composition(
            tmp_path,
            extra="analysis:\n  scoreboards: [{name: sbd, source: topcmd}]\n"
            "  coverage: [topcmd]\n",
        )
    # ... and without the collector, the single-stream scoreboard is refused too
    with pytest.raises(ValueError, match="composition scoreboard is two-stream"):
        _composition(
            tmp_path, extra="analysis:\n  scoreboards: [{name: sbd, source: topcmd}]\n"
        )
    # the plain bench takes it: there the report was true
    _cfg(analysis=pair)


def test_the_cli_reports_the_instances_section(tmp_path):
    cfg = tmp_path / "y.yaml"
    cfg.write_text(
        "project: {name: y}\n"
        "dut: {name: y, clock: clk, reset: rst_n}\n"
        "agents:\n"
        "  - name: pkt\n"
        "    interface: pkt_if\n"
        "    sequence_item: pkt_item\n"
        "    replicas: 2\n"
        "    ports:\n"
        "      inputs:  [{name: in_valid, width: 1}]\n"
        "      outputs: [{name: out_valid, width: 1}]\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from quick_uvm.cli import main; main()",
            "resolve",
            "-c",
            str(cfg),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    r = json.loads(out.stdout)
    assert r["analysis"] == {"mode": "implicit", "scoreboards": [], "coverage": []}
    assert [i["scoreboard"]["name"] for i in r["instances"]] == ["pkt_0_sb", "pkt_1_sb"]


# Every committed example, against the files it ships. `gen/` is the generator's own
# output (test_example_byte_identity.py holds it to that), so this compares the
# report with what the templates wrote, without regenerating anything. It covers
# the shapes the examples HAVE -- none of them arms a guard, none is a hybrid
# with an unchecked boundary agent, none has a `wired: false` entry other than the
# two `replicas` scoreboards; those are the generated cases above.
def _example_dirs():
    return sorted(
        {p.parent for p in _EX.glob("*/gen") if p.is_dir()}, key=lambda p: p.name
    )


@pytest.mark.parametrize("example", _example_dirs(), ids=lambda p: p.name)
def test_every_committed_example_agrees_with_its_env(example):
    cfg = ProjectConfig.from_yaml(example / f"{example.name}.yaml")
    gen = example / "gen"
    hits = list(gen.rglob(f"{cfg.dut.name}_env.svh"))
    env = hits[0].read_text(encoding="utf-8") if hits else ""
    r = cfg.resolved()
    name = example.name

    # scoreboards and collectors, both ways: the env declares exactly the handles
    # the report names -- inferred, declared, per-instance, cross-block
    env_sbs, env_cov = _declared_by(env)
    rep_sbs, rep_cov = _reported_by(r)
    assert env_sbs == rep_sbs, f"{name}: scoreboards, env vs resolve"
    # (the register model's access coverage is `register_model.coverage`, written
    # in the YAML under its own key: a collector of another kind, not analysis)
    rm = cfg.register_model
    reg_cov = {"reg_cov_h"} if rm is not None and rm.coverage else set()
    assert env_cov == rep_cov | reg_cov, f"{name}: collectors, env vs resolve"
    assert cfg.is_vip or bool(hits), f"{name}: a bench without an env file"

    # the guards: armed in the env exactly when reported
    for guard in ("UNCHECKED_AGENT", "UNCOVERED_AGENT"):
        reported = any(g.startswith(f"{guard}:") for g in r["guards"])
        assert (f'"{guard}"' in env) == reported, f"{name}: {guard}, env vs resolve"

    # the inferred virtual sequence and the tests, ONE way: what is reported is
    # shipped. (Not the reverse: a `register_model` ships `<dut>_reg_test` and its
    # `csr_tests`, which `resolve` does not list -- a known gap, in the changelog.)
    inferred_vseqs = [
        v["name"] for v in r["virtual_sequences"] if v["origin"] == "inferred"
    ]
    for v in inferred_vseqs:
        assert list(gen.rglob(f"{v}.svh")), f"{name}: no file for the vseq {v}"
    if not r["virtual_sequences"]:
        assert not list(gen.rglob(f"{cfg.dut.name}_vseq.svh")), (
            f"{name}: ships a top virtual sequence resolve does not report"
        )
    for t in r["tests"]:
        assert list(gen.rglob(f"{t['name']}.svh")), f"{name}: no file for {t['name']}"
    if cfg.is_vip:
        assert r["tests"] == [] and not list(gen.rglob("*_test*.svh"))
