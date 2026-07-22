"""Track A — the generation manifest (element → files) + repeatable `--only`.

The manifest is the single source of truth for per-item incremental regen and
QuickUVM Architect's "not generated" decorations: it maps each config ELEMENT to
its generated files (keyed by the element's own name, not the possibly-name-dropped
filename), plus an `aggregate` group of whole-config files that must be
co-regenerated on any structural add/remove/rename."""

from pathlib import Path

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig


def _cfg(**over):
    base = {
        "project": {"name": "d_tb"},
        "dut": {"name": "d", "clock": "clk", "reset": "rst_n"},
        "agents": [
            {
                "name": "cmd",
                "interface": "cmd_if",
                "sequence_item": "cmd_seq_item",
                "ports": {
                    "inputs": [{"name": "req", "width": 8}],
                    "outputs": [{"name": "ack", "width": 8}],
                },
            }
        ],
        "tests": [{"name": "t1"}],
    }
    base.update(over)
    return base


def _owners(manifest):
    return {e["owner"] for e in manifest["elements"]}


def _files_of(manifest, owner):
    for e in manifest["elements"]:
        if e["owner"] == owner:
            return [f["file"] for f in e["files"]]
    return []


# --- manifest shape -----------------------------------------------------------


def test_manifest_groups_by_element():
    m = Generator(ProjectConfig.model_validate(_cfg())).manifest()
    assert m["layout"] == "flat" and m["kind"] == "bench"
    owners = _owners(m)
    assert "agent:cmd" in owners
    assert "scoreboard:sbd" in owners  # implicit scoreboard, keyed by NAME not filename
    assert "test:t1" in owners
    assert "aggregate" in owners
    # the agent's files are attributed to it, not to aggregate
    agent_files = _files_of(m, "agent:cmd")
    assert "cmd_agent.svh" in agent_files and "cmd_if.sv" in agent_files
    # the flat scoreboard's file is DUT-prefixed but owned by scoreboard:sbd
    assert "d_scoreboard.svh" in _files_of(m, "scoreboard:sbd")
    # whole-config files land in aggregate
    agg = _files_of(m, "aggregate")
    assert "d_tb_pkg.sv" in agg and "pkg.f" in agg and "clkgen.sv" in agg


def test_manifest_covers_every_file_exactly_once():
    cfg = ProjectConfig.model_validate(_cfg())
    m = Generator(cfg).manifest()
    manifest_files = sorted(f["file"] for e in m["elements"] for f in e["files"])
    spec_files = sorted(s.output for s in Generator(cfg).files_to_generate())
    assert manifest_files == spec_files  # partition: no file lost, none duplicated


def test_manifest_named_scoreboards_and_tests():
    cfg = ProjectConfig.model_validate(
        _cfg(
            agents=[
                {
                    "name": "cmd",
                    "interface": "cmd_if",
                    "sequence_item": "cmd_seq_item",
                    "ports": {"inputs": [{"name": "req", "width": 8}]},
                },
                {
                    "name": "rsp",
                    "interface": "rsp_if",
                    "sequence_item": "rsp_seq_item",
                    "ports": {"outputs": [{"name": "ack", "width": 8}]},
                },
            ],
            analysis={
                "scoreboards": [
                    {"name": "sa", "source": "cmd"},
                    {"name": "sb", "source": "rsp"},
                ]
            },
            tests=[{"name": "t1"}, {"name": "t2"}],
        )
    )
    m = Generator(cfg).manifest()
    owners = _owners(m)
    assert {"scoreboard:sa", "scoreboard:sb", "test:t1", "test:t2"} <= owners
    assert "d_sa_scoreboard.svh" in _files_of(m, "scoreboard:sa")


def test_manifest_exists_flags(tmp_path: Path):
    cfg = ProjectConfig.model_validate(_cfg())
    Generator(cfg).generate_all(tmp_path)
    m = Generator(cfg).manifest(output_dir=tmp_path)
    for e in m["elements"]:
        for f in e["files"]:
            assert f["exists"] is True  # everything was just generated
    # a fresh dir → nothing exists
    m2 = Generator(cfg).manifest(output_dir=tmp_path / "empty")
    assert all(not f["exists"] for e in m2["elements"] for f in e["files"])


# --- repeatable --only --------------------------------------------------------


def test_only_scopes_to_the_listed_files(tmp_path: Path):
    cfg = ProjectConfig.model_validate(_cfg())
    Generator(cfg).generate_all(tmp_path)  # full first
    # regenerate only two files; a str-or-iterable `only`
    results = Generator(cfg).generate_all(
        tmp_path, only=["cmd_driver.svh", "cmd_monitor.svh"]
    )
    written = sorted(Path(p).name for _s, p in results)
    assert written == ["cmd_driver.svh", "cmd_monitor.svh"]


def test_only_single_string_still_works(tmp_path: Path):
    cfg = ProjectConfig.model_validate(_cfg())
    Generator(cfg).generate_all(tmp_path)
    results = Generator(cfg).generate_all(tmp_path, only="cmd_agent.svh")
    assert [Path(p).name for _s, p in results] == ["cmd_agent.svh"]
