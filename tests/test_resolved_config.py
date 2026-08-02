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
import subprocess
import sys

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
