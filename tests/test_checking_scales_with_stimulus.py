"""Checking must scale with stimulus (schema-philosophy-audit, PR 4).

The audit's beginner-path finding: with `auto_virtual_sequences: true` (the
default), adding a second agent auto-drives BOTH agents' sequences in parallel
— but the default analysis wiring scoreboards only the FIRST agent, silently.
The natural second step of a beginner produced a driven-but-unchecked stream
and a green bench: the silent-pass shape one agent over from the
UNFILLED_PREDICTOR fatal that guards agent #1.

The calibration matters: REFUSING (a validation wall) would tax the simple
case — two agents must still just work, and the auto-vseq feature's own tests
drive multiple agents bare. So this is the UNFILLED_PREDICTOR pattern at
proportionate severity: the generated env raises a loud UNCHECKED_AGENT
uvm_warning per driven-but-unchecked agent, in every simulation log, counted
in the UVM severity block users read. Declaring any `analysis:` block (even
primary-only, made explicit) is the routing intent that silences it. Empty
for every committed example (all multi-agent examples declare `analysis:`),
so the guard is byte-identical wherever it does not apply.
"""

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig


def _agent(name, **over):
    a = {
        "name": name,
        "interface": f"{name}_if",
        "sequence_item": f"{name}_item",
        "ports": {
            "inputs": [{"name": f"{name}_in", "width": 8}],
            "outputs": [{"name": f"{name}_out", "width": 8}],
        },
    }
    a.update(over)
    return a


def _cfg(agents, **over):
    base = {
        "project": {"name": "t", "author": "x"},
        "dut": {"name": "d", "clock": "clk", "reset": "rst_n"},
        "agents": agents,
        "tests": [{"name": "rand_test"}],
    }
    base.update(over)
    return ProjectConfig.model_validate(base)


def _env(tmp_path, cfg):
    Generator(cfg).generate_all(tmp_path, backup=False)
    return (tmp_path / "d_env.svh").read_text()


def test_two_driven_agents_without_analysis_warn(tmp_path):
    cfg = _cfg([_agent("a"), _agent("b")])
    assert cfg.unchecked_stimulus_agents == ["b"]
    env = _env(tmp_path, cfg)
    assert "UNCHECKED_AGENT" in env
    assert "agent 'b' is driven by the auto virtual sequence" in env
    # the primary agent IS scoreboarded — never listed
    assert "agent 'a' is driven" not in env


def test_analysis_block_silences_the_warning(tmp_path):
    cfg = _cfg(
        [_agent("a"), _agent("b")],
        analysis={
            "coverage": [],
            "scoreboards": [{"name": "sbd", "source": "a"}],
        },
    )
    assert cfg.unchecked_stimulus_agents == []
    assert "UNCHECKED_AGENT" not in _env(tmp_path, cfg)


def test_single_agent_emits_no_warning(tmp_path):
    cfg = _cfg([_agent("a")])
    assert cfg.unchecked_stimulus_agents == []
    assert "UNCHECKED_AGENT" not in _env(tmp_path, cfg)


def test_passive_second_agent_emits_no_warning(tmp_path):
    """A passive agent is not driven — the guard keys on STIMULUS agents."""
    cfg = _cfg([_agent("a"), _agent("b", active=False)])
    assert cfg.unchecked_stimulus_agents == []
    assert "UNCHECKED_AGENT" not in _env(tmp_path, cfg)


def test_auto_vseq_off_emits_no_warning(tmp_path):
    """With auto_virtual_sequences off only the primary is driven — no
    driven-but-unchecked stream exists (the second agent is idle)."""
    cfg = _cfg([_agent("a"), _agent("b")], auto_virtual_sequences=False)
    assert cfg.unchecked_stimulus_agents == []
    assert "UNCHECKED_AGENT" not in _env(tmp_path, cfg)


def test_responder_second_agent_emits_no_warning(tmp_path):
    """A responder is not auto-driven (its sequencer is owned by its forever
    responder sequence) — the guard keys on stimulus agents only."""
    resp = _agent(
        "mem",
        mode="responder",
        request_valid="req",
        ports={
            "inputs": [{"name": "gnt", "width": 1}],
            "outputs": [{"name": "req", "width": 1}, {"name": "addr", "width": 8}],
        },
    )
    cfg = _cfg([_agent("a"), resp])
    assert cfg.unchecked_stimulus_agents == []
    assert "UNCHECKED_AGENT" not in _env(tmp_path, cfg)


def test_three_agents_lists_both_unchecked(tmp_path):
    cfg = _cfg([_agent("a"), _agent("b"), _agent("c")])
    assert cfg.unchecked_stimulus_agents == ["b", "c"]
    env = _env(tmp_path, cfg)
    assert "agent 'b' is driven" in env
    assert "agent 'c' is driven" in env
