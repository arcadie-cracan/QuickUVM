"""Walls for the three silent-misgen holes (schema-philosophy-audit, PR 2).

Each of these configs used to VALIDATE and then generate a bench that silently
did something other than what the config said:

* `register_model.bus_agent` naming a responder bound the RAL front door to a
  sequencer the forever responder sequence owns — the sequencer-clobber trap
  already walled (with the same prose) for tests[].sequence and vseq steps;
* a test's `sequence:` selector on a `replicas`/`instances` bench was validated,
  then the per-replica test body started each replica's DEFAULT sequence — the
  test ran a different sequence than the one it named, and passed;
* `kind: vip` rejected subenvs/register_model/connections but silently dropped
  tests/analysis/probes/virtual_sequences/regress/subenv_scoreboards.
"""

import pytest
from pydantic import ValidationError

from quick_uvm.models import ProjectConfig

_RESP_PORTS = {
    "inputs": [{"name": "gnt", "width": 1}, {"name": "rdata", "width": 32}],
    "outputs": [{"name": "req", "width": 1}, {"name": "addr", "width": 8}],
}


def _cfg(**over):
    base = {
        "project": {"name": "t", "author": "x"},
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
    base.update(over)
    return base


# --- 1. RAL front door on a responder sequencer -------------------------------


def test_bus_agent_rejects_responder():
    cfg = _cfg(
        agents=[
            {
                "name": "mem",
                "interface": "mem_if",
                "sequence_item": "mem_item",
                "mode": "responder",
                "request_valid": "req",
                "ports": _RESP_PORTS,
            }
        ],
        register_model={
            "package": "p_pkg",
            "block": "p_blk",
            "bus_agent": "mem",
        },
    )
    with pytest.raises(ValidationError, match="RESPONDER.*answer garbage"):
        ProjectConfig.model_validate(cfg)


def test_bus_agent_allows_proactive_hybrid():
    """A `proactive: true` hybrid is exempt, matching the tests/vseq doors."""
    cfg = _cfg(
        agents=[
            {
                "name": "mem",
                "interface": "mem_if",
                "sequence_item": "mem_item",
                "mode": "responder",
                "request_valid": "req",
                "proactive": True,
                "ports": _RESP_PORTS,
            }
        ],
        register_model={
            "package": "p_pkg",
            "block": "p_blk",
            "bus_agent": "mem",
        },
    )
    ProjectConfig.model_validate(cfg)  # must not raise


# --- 2. tests[].sequence on a multi-instance bench ----------------------------


def test_sequence_selector_rejected_with_count():
    cfg = _cfg(
        dut={"name": "d", "clock": "clk", "reset": "rst_n", "external_reset": True},
        agents=[
            {
                "name": "ch",
                "interface": "ch_if",
                "sequence_item": "ch_item",
                "replicas": 3,
                "sequences": [{"name": "burst", "kind": "random"}],
                "ports": {
                    "inputs": [{"name": "a", "width": 1}],
                    "outputs": [{"name": "b", "width": 1}],
                },
            }
        ],
        tests=[{"name": "t1", "sequence": {"agent": "ch", "name": "burst"}}],
    )
    with pytest.raises(ValidationError, match="silently ignore the selector"):
        ProjectConfig.model_validate(cfg)


def test_sequence_selector_rejected_with_instances():
    cfg = _cfg(
        agents=[
            {
                "name": "pi",
                "interface": "pi_if",
                "sequence_item": "pi_item",
                "parameters": [{"name": "W", "default": 8}],
                "instances": [
                    {"name": "i8", "values": {"W": 8}},
                    {"name": "i16", "values": {"W": 16}},
                ],
                "sequences": [{"name": "burst", "kind": "random"}],
                "ports": {
                    "inputs": [{"name": "a", "width_param": "W"}],
                    "outputs": [{"name": "b", "width_param": "W"}],
                },
            }
        ],
        tests=[{"name": "t1", "sequence": {"agent": "pi", "name": "burst"}}],
    )
    with pytest.raises(ValidationError, match="silently ignore the selector"):
        ProjectConfig.model_validate(cfg)


def test_sequence_selector_fine_on_single_instance():
    cfg = _cfg(
        agents=[
            {
                "name": "m",
                "interface": "m_if",
                "sequence_item": "m_item",
                "sequences": [{"name": "burst", "kind": "random"}],
                "ports": {
                    "inputs": [{"name": "din", "width": 8}],
                    "outputs": [{"name": "dout", "width": 8}],
                },
            }
        ],
        tests=[{"name": "t1", "sequence": {"agent": "m", "name": "burst"}}],
    )
    ProjectConfig.model_validate(cfg)  # must not raise


# --- 3. the kind:vip fence covers every dropped section -----------------------

_VIP_BASE = {
    "project": {"name": "v", "author": "x", "version": "1.0.0"},
    "kind": "vip",
    "layout": "packaged",
    "agents": [
        {
            "name": "io",
            "interface": "io_if",
            "sequence_item": "io_item",
            "ports": {
                "inputs": [{"name": "a", "width": 1}],
                "outputs": [{"name": "b", "width": 1}],
            },
        }
    ],
}


@pytest.mark.parametrize(
    "section, value",
    [
        ("tests", [{"name": "t1"}]),
        ("analysis", {"coverage": ["io"], "scoreboards": []}),
        (
            "probes",
            [{"name": "lvl", "path": "u.q", "width": 4}],
        ),
        (
            "virtual_sequences",
            [{"name": "vs", "body": [{"agent": "io", "sequence": "io_seq"}]}],
        ),
        ("regress", {"seeds": 2}),
    ],
)
def test_vip_fence_rejects_dropped_sections(section, value):
    with pytest.raises(ValidationError, match="silently dropped"):
        ProjectConfig.model_validate({**_VIP_BASE, section: value})


def test_vip_with_coverage_models_still_fine():
    """coverage_models is CONSUMED by the agent package (<ag>_cov.svh) — not fenced."""
    cfg = {
        **_VIP_BASE,
        "coverage_models": [
            {
                "agent": "io",
                "coverpoints": [{"field": "a", "bins": [{"name": "z", "value": 0}]}],
            }
        ],
    }
    ProjectConfig.model_validate(cfg)  # must not raise
