"""Fail-closed at the KEY layer (the schema-philosophy-audit hardening).

The value layer has always been fail-closed (245 rationale-bearing validators);
this closes the two fail-open neighbors the audit found:

* unknown/stale/typo'd YAML keys were silently ignored in 31/33 classes — a
  misspelled `analyses:` block or a pre-rename `trans_style:` validated fine and
  the config it carried simply vanished from the bench;
* runtime-only fields (set by the loader after validation) were accepted as user
  input — plain-yaml `is_reference: true` fabricated a reference to a VIP that
  does not exist, and `clocks:` acted as a broken alias of the `clock:` list.

Plus the front-door regression gate: every full-config YAML block in README.md
must validate against ProjectConfig (the audit found the documented quickstart
used pre-rename keys and failed validation).
"""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from quick_uvm.models import ProjectConfig

_BASE = {
    "project": {"name": "t", "author": "a@b.c"},
    "dut": {"name": "d", "clock": "clk", "reset": "rst_n"},
    "agents": [
        {
            "name": "m",
            "interface": "m_if",
            "sequence_item": "m_item",
            "ports": {
                "inputs": [{"name": "din", "width": 8}],
                "outputs": [{"name": "dout", "width": 8}],
            },
        }
    ],
    "tests": [{"name": "rand_test"}],
}


def _with_agent(**extra):
    cfg = {**_BASE, "agents": [{**_BASE["agents"][0], **extra}]}
    return cfg


# --- unknown keys are rejected everywhere (extra="forbid" via the shared base) --


def test_unknown_agent_key_rejected():
    with pytest.raises(ValidationError, match="[Ee]xtra"):
        ProjectConfig.model_validate(_with_agent(trans_stylo="manual"))


def test_unknown_toplevel_block_rejected():
    """A misspelled section (`analyses:` for `analysis:`) must not silently
    vanish — before this gate it generated a default bench with the intended
    scoreboard/coverage config gone."""
    with pytest.raises(ValidationError, match="[Ee]xtra"):
        ProjectConfig.model_validate({**_BASE, "analyses": {"coverage": ["m"]}})


def test_unknown_nested_key_rejected():
    with pytest.raises(ValidationError, match="[Ee]xtra"):
        ProjectConfig.model_validate(
            {**_BASE, "tests": [{"name": "t1", "num_item": 5}]}  # typo of num_items
        )


# --- the known renames get teaching errors, not a bare "extra" ----------------


def test_pre_rename_transaction_key_errors_with_hint():
    with pytest.raises(ValidationError, match="renamed to 'sequence_item"):
        ProjectConfig.model_validate(_with_agent(transaction="m_item"))


def test_pre_rename_trans_style_key_errors_with_hint():
    with pytest.raises(ValidationError, match="renamed to 'seq_item_style"):
        ProjectConfig.model_validate(_with_agent(trans_style="manual"))


def test_pre_rename_count_key_errors_with_hint():
    """Agent-level `count:` became `replicas:` (identical copies x one vectored
    DUT — named for what it means, and no longer a homonym of the sequence/test
    item counts, which keep their natural spelling)."""
    with pytest.raises(ValidationError, match="renamed to 'replicas"):
        ProjectConfig.model_validate(_with_agent(count=3))


# --- runtime-only fields are not valid user input -----------------------------


def test_agent_runtime_fields_rejected():
    for key, val in (
        ("is_reference", True),
        ("ref_filelist", "/tmp/x.f"),
        ("original_name", "m0"),
    ):
        with pytest.raises(ValidationError, match="internal"):
            ProjectConfig.model_validate(_with_agent(**{key: val}))


def test_toplevel_runtime_fields_rejected():
    with pytest.raises(ValidationError, match="internal"):
        ProjectConfig.model_validate({**_BASE, "clocks": [{"name": "a", "period": 10}]})
    with pytest.raises(ValidationError, match="internal"):
        ProjectConfig.model_validate({**_BASE, "original_dut_name": "x"})


def test_clock_list_syntax_still_works():
    """The LEGIT multi-clock spelling — `clock:` as a list — is untouched."""
    cfg = ProjectConfig.model_validate(
        {
            **_BASE,
            "clock": [
                {"name": "clk_a", "period": 10},
                {"name": "clk_b", "period": 7},
            ],
        }
    )
    assert [c.name for c in cfg.effective_clocks] == ["clk_a", "clk_b"]


def test_agent_refs_path_still_marks_references(tmp_path):
    """from_yaml still marks referenced agents — now POST-validation (the
    runtime fields never transit the input dict)."""
    vip = tmp_path / "vip"
    vip.mkdir()
    (vip / "io_pkg.f").write_text("io_pkg.sv\n")
    (vip / "v.qvip").write_text(
        yaml.safe_dump(
            {
                "qvip_version": 1,
                "project": "v",
                "agents": {
                    "io": {
                        "package": "io_pkg",
                        "filelist": "io_pkg.f",
                        "interface": "io_if",
                        "sequence_item": "io_item",
                        "config": {
                            "name": "io",
                            "interface": "io_if",
                            "sequence_item": "io_item",
                            "ports": {
                                "inputs": [{"name": "a", "width": 1}],
                                "outputs": [{"name": "b", "width": 1}],
                            },
                        },
                    }
                },
            }
        )
    )
    con = {
        **_BASE,
        "layout": "packaged",
        "agent_refs": [{"name": "io", "manifest": "vip/v.qvip"}],
    }
    p = tmp_path / "con.yaml"
    p.write_text(yaml.safe_dump(con))
    cfg = ProjectConfig.from_yaml(p)
    ref = next(a for a in cfg.agents if a.name == "io")
    assert ref.is_reference
    assert ref.ref_filelist.endswith("io_pkg.f")


# --- the front door: README config blocks must validate -----------------------


def _readme_full_configs():
    """Every ```yaml block in README.md that looks like a FULL config (has both
    `project:` and `dut:`) — fragments are skipped."""
    text = (Path(__file__).parent.parent / "README.md").read_text()
    for block in re.findall(r"```yaml\n(.*?)```", text, re.DOTALL):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            pytest.fail(f"README.md yaml block does not parse:\n{block[:200]}")
        if isinstance(data, dict) and "project" in data and "dut" in data:
            yield data


def test_readme_config_blocks_validate():
    blocks = list(_readme_full_configs())
    assert blocks, "README.md no longer contains a full-config yaml block?"
    for data in blocks:
        ProjectConfig.model_validate(data)  # raises on a broken front door
