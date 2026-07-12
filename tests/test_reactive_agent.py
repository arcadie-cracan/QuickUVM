"""Reactive / responder (device) agent — the two shapes.

The DUT initiates; the agent responds. See docs/reactive_agent_investigation.md.

The two shapes exist because of the protocol, not taste:
  * BLOCKING   — parks on get_next_item when it has no item. The driver loop is the
                 initiator's, UNCHANGED.
  * CONTINUOUS — the DUT samples our outputs every cycle, so parking would leave them
                 stale or X. Non-blocking try_next_item + drive-idle-on-miss.
Declaring `idle:` selects the continuous shape — the data IS the knob.
"""

import pytest
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

# A device agent: the DUT drives req/addr (we SAMPLE), we drive gnt/rdata (the RESPONSE).
# NB the port-direction model is unchanged — `inputs` are still what the agent drives.
_BASE = {
    "project": {"name": "d_tb", "author": "a@b.c"},
    "dut": {"name": "d", "clock": "clk", "reset": "rst_n", "external_reset": True},
    "agents": [
        {
            "name": "mem",
            "interface": "mem_if",
            "sequence_item": "mem_seq_item",
            "mode": "responder",
            "request_valid": "req",
            "ports": {
                "inputs": [
                    {"name": "gnt", "width": 1, "randomize": True},
                    {"name": "rdata", "width": 32, "randomize": True},
                ],
                "outputs": [
                    {"name": "req", "width": 1},
                    {"name": "addr", "width": 8},
                ],
            },
        }
    ],
    "tests": [{"name": "rand_test"}],
}


def _gen(tmp_path, **over):
    agents = over.pop("agents", None)
    cfg_d = {**_BASE, **over}
    if agents:
        cfg_d["agents"] = agents
    cfg = ProjectConfig.model_validate(cfg_d)
    Generator(cfg).generate_all(tmp_path, backup=False)
    return cfg


def _initiator(**over):
    a = {**_BASE["agents"][0]}
    a.pop("mode", None)
    a.pop("request_valid", None)
    a.update(over)
    return [a]


# --- opt-in / byte-identity -------------------------------------------------


def test_initiator_emits_no_responder_artifacts(tmp_path):
    _gen(tmp_path, agents=_initiator())
    assert not (tmp_path / "mem_responder_seq.svh").exists()
    drv = (tmp_path / "mem_driver.svh").read_text()
    assert "try_next_item" not in drv
    assert "drive_idle" not in drv
    sqr = (tmp_path / "mem_sequencer.svh").read_text()
    assert "request_fifo" not in sqr
    mon = (tmp_path / "mem_monitor.svh").read_text()
    assert "request_ap" not in mon


# --- the BLOCKING shape -----------------------------------------------------


def test_blocking_responder_driver_loop_is_the_initiator_loop(tmp_path):
    """No `idle:` => the blocking shape. The load-bearing simplification: the driver
    loop is EXACTLY the initiator's, so reactivity costs nothing in the driver."""
    _gen(tmp_path)
    drv = (tmp_path / "mem_driver.svh").read_text()
    assert "seq_item_port.get_next_item(tr);" in drv
    assert "try_next_item" not in drv
    assert "drive_idle" not in drv


def test_responder_emits_the_reactive_machinery(tmp_path):
    _gen(tmp_path)
    # monitor publishes the REQUEST on a second port, qualified by request_valid
    mon = (tmp_path / "mem_monitor.svh").read_text()
    assert "request_ap" in mon
    assert "if (tr.req) request_ap.write(tr);" in mon
    # sequencer gains the blocking rendezvous
    sqr = (tmp_path / "mem_sequencer.svh").read_text()
    assert "uvm_tlm_analysis_fifo" in sqr
    assert "request_export.connect(request_fifo.analysis_export);" in sqr
    # the agent wires it, gated on is_active, and OWNS the responder
    agt = (tmp_path / "mem_agent.svh").read_text()
    assert "mon.request_ap.connect(sqr.request_export);" in agt
    assert "responder.start(sqr);" in agt
    # the forever responder sequence, with the user seam
    seq = (tmp_path / "mem_responder_seq.svh").read_text()
    assert "p_sequencer.request_fifo.get(req);" in seq
    assert "pragma quickuvm custom response_logic" in seq


def test_responder_is_owned_by_the_agent_not_a_phase_default_sequence(tmp_path):
    """A phase `default_sequence` is KILLED when its phase ends — and a responder raises
    no objection, so it would be torn down instantly. The agent forks it instead."""
    _gen(tmp_path)
    base = (tmp_path / "d_base_test.svh").read_text()
    assert "default_sequence" not in base
    agt = (tmp_path / "mem_agent.svh").read_text()
    assert "responder.start(sqr);" in agt


def test_test_does_not_start_stimulus_on_a_responder(tmp_path):
    """Two sequences on one sequencer would fight over the driver: the random items
    would clobber the computed responses, and the bench would 'pass' answering garbage."""
    cfg = _gen(tmp_path)
    assert cfg.responder_only
    assert cfg.stimulus_agents == []
    test = (tmp_path / "rand_test.svh").read_text()
    assert "seq.start" not in test
    assert "@(posedge env_cfg.mem_cfg.vif.clk)" in test


# --- the CONTINUOUS shape ---------------------------------------------------


def _continuous():
    a = {**_BASE["agents"][0], "idle": {"gnt": 0, "rdata": 0}}
    return [a]


def test_idle_selects_the_continuous_shape(tmp_path):
    cfg = _gen(tmp_path, agents=_continuous())
    assert cfg.agents[0].is_continuous
    drv = (tmp_path / "mem_driver.svh").read_text()
    assert "seq_item_port.try_next_item(tr);" in drv
    assert "drive_idle();" in drv
    # the declared idle values are what it drives on a miss
    assert "vif.cb1.gnt <= 1'd0;" in drv
    assert "vif.cb1.rdata <= 32'd0;" in drv
    # ...and a seam for the per-cycle protocol thread (a combinational grant, say) —
    # protocol logic is never generated.
    assert "pragma quickuvm custom driver_threads" in drv


# --- fail-closed validation -------------------------------------------------


def test_rejects_idle_on_an_initiator():
    a = _initiator(idle={"gnt": 0})
    with pytest.raises(ValidationError, match="only valid with `mode: responder`"):
        ProjectConfig.model_validate({**_BASE, "agents": a})


def test_rejects_request_valid_on_an_initiator():
    a = _initiator(request_valid="req")
    with pytest.raises(ValidationError, match="only valid with `mode: responder`"):
        ProjectConfig.model_validate({**_BASE, "agents": a})


def test_rejects_responder_without_request_valid():
    a = {**_BASE["agents"][0]}
    a.pop("request_valid")
    with pytest.raises(ValidationError, match="requires `request_valid`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_request_valid_naming_a_driven_port():
    """request_valid must name a SAMPLED port — the DUT drives the request."""
    a = {**_BASE["agents"][0], "request_valid": "gnt"}
    with pytest.raises(ValidationError, match="must name one of this agent's SAMPLED"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_idle_naming_a_sampled_port():
    """idle keys must name DRIVEN ports — you cannot drive an idle value onto a port the
    DUT drives."""
    a = {**_BASE["agents"][0], "idle": {"req": 0}}
    with pytest.raises(ValidationError, match="must be one of this agent's DRIVEN"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_idle_value_too_wide():
    a = {**_BASE["agents"][0], "idle": {"gnt": 2}}
    with pytest.raises(ValidationError, match="does not fit"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_passive_responder():
    """Reactive is NOT passive — a reactive slave DRIVES its response."""
    a = {**_BASE["agents"][0], "active": False}
    with pytest.raises(ValidationError, match="requires `active: true`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_responder_with_nothing_to_drive():
    a = {**_BASE["agents"][0]}
    a["ports"] = {"inputs": [], "outputs": [{"name": "req", "width": 1}]}
    with pytest.raises(ValidationError, match="nothing to drive as a response"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_multibit_request_valid():
    a = {**_BASE["agents"][0], "request_valid": "addr"}
    with pytest.raises(ValidationError, match="must be 1 bit"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


# --- the MIXED bench (the real case: spi_host = host agent + device agent) ---

_MIXED = {
    "project": {"name": "mx_tb", "author": "a@b.c"},
    "dut": {"name": "mx", "clock": "clk", "reset": "rst_n", "external_reset": True},
    "agents": [
        # agents[0] is deliberately the RESPONDER — the trap.
        {
            "name": "dev",
            "interface": "dev_if",
            "sequence_item": "dev_item",
            "mode": "responder",
            "request_valid": "req",
            "ports": {
                "inputs": [{"name": "gnt", "width": 1, "randomize": True}],
                "outputs": [{"name": "req", "width": 1}],
            },
        },
        {
            "name": "host",
            "interface": "host_if",
            "sequence_item": "host_item",
            "ports": {
                "inputs": [{"name": "cmd", "width": 8, "randomize": True}],
                "outputs": [{"name": "stat", "width": 8}],
            },
        },
    ],
    "tests": [{"name": "rand_test"}],
}


def test_mixed_bench_never_starts_stimulus_on_the_responder(tmp_path):
    """THE REAL CASE (spi_host: a host agent + a device agent), and the trap: agents[0] is
    the responder. The test must start stimulus on the INITIATOR. Starting it on the
    responder's sequencer would clobber the computed responses with random items — the
    device would answer garbage while the bench reported PASS.
    """
    cfg = ProjectConfig.model_validate(_MIXED)
    assert cfg.primary_agent.name == "dev"  # agents[0] IS the responder
    assert cfg.stimulus_primary.name == "host"  # ...but stimulus goes to the initiator
    assert not cfg.responder_only

    Generator(cfg).generate_all(tmp_path, backup=False)
    test = (tmp_path / "rand_test.svh").read_text()
    assert "seq.start(e.host_agnt.sqr);" in test
    assert "dev_agnt.sqr" not in test


def test_auto_vseq_excludes_responders(tmp_path):
    """The auto-vseq fires every active agent's default sequence. A responder must never
    be among them."""
    agents = _MIXED["agents"] + [
        {
            "name": "host2",
            "interface": "host2_if",
            "sequence_item": "host2_item",
            "ports": {
                "inputs": [{"name": "c2", "width": 8, "randomize": True}],
                "outputs": [{"name": "s2", "width": 8}],
            },
        }
    ]
    cfg = ProjectConfig.model_validate({**_MIXED, "agents": agents})
    # two STIMULUS agents -> an auto-vseq exists...
    assert cfg.auto_vseq_name == "mx_vseq"
    steps = [s.agent for s in cfg.effective_virtual_sequences[0].body]
    # ...and it coordinates only them, never the responder.
    assert steps == ["host", "host2"]
    Generator(cfg).generate_all(tmp_path, backup=False)
    vseq = (tmp_path / "mx_vseq.svh").read_text()
    assert "dev_seq" not in vseq


def test_rejects_an_explicit_vseq_step_on_a_responder():
    cfg = {
        **_MIXED,
        "virtual_sequences": [
            {"name": "mx_v", "body": [{"agent": "dev", "sequence": "dev_seq"}]}
        ],
    }
    with pytest.raises(ValidationError, match="targets RESPONDER agent"):
        ProjectConfig.model_validate(cfg)
