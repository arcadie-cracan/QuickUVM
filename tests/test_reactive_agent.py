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

# A device agent: the DUT drives req/addr (we SAMPLE), we drive gnt/rdata (the
# RESPONSE).
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
    # published on the RISING EDGE of the qualifier, not its level: a request line is
    # held until granted, so a level publish would queue one copy per cycle and the
    # responder would answer the same request many times.
    assert "if (tr.req && !m_req_seen) request_ap.write(tr);" in mon
    assert "m_req_seen = tr.req;" in mon
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


# --- holes found by the pre-merge adversarial review -------------------------
# Every one of these let random stimulus reach a responder's sequencer, or let a dead
# responder report PASS. They are the same failure mode this feature keeps producing, so
# each gets a test rather than a comment.


def test_rejects_a_test_sequence_targeting_a_responder():
    """The vseq guard covered only VIRTUAL sequences. A single-agent `test.sequence` on a
    responder was still accepted — and it would clobber the computed responses.

    The sequence must be a DECLARED library sequence of that agent, or an earlier
    validator rejects it first for an unrelated reason and this hole stays open.
    """
    import copy

    cfg = copy.deepcopy(_MIXED)
    cfg["agents"][0]["sequences"] = [{"name": "dev_err_seq", "kind": "directed"}]
    cfg["tests"] = [{"name": "t", "sequence": {"agent": "dev", "name": "dev_err_seq"}}]
    with pytest.raises(ValidationError, match="targets RESPONDER agent"):
        ProjectConfig.model_validate(cfg)


def test_rejects_responder_with_c3_instances():
    """The generated test's `has_instances` branch starts per-instance RANDOM stimulus on
    every instance's sequencer — a responder's included."""
    a = {
        **_BASE["agents"][0],
        "parameters": [{"name": "W", "default": 32}],
        "instances": [{"name": "i0", "values": {"W": 8}}],
    }
    with pytest.raises(ValidationError, match="not yet supported with C3 `instances`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_monitor_publishes_the_request_once_not_every_cycle(tmp_path):
    """A request line is HELD until granted. A level-triggered publish queues one copy per
    cycle and the responder answers the same request many times."""
    _gen(tmp_path)
    mon = (tmp_path / "mem_monitor.svh").read_text()
    assert "if (tr.req && !m_req_seen) request_ap.write(tr);" in mon
    assert "m_req_seen = tr.req;" in mon


def test_continuous_driver_parks_at_the_declared_idle_values(tmp_path):
    """initialize() used to park at hardcoded '1/'0, so the bus carried the WRONG idle
    level (often inverted) until the first item arrived."""
    _gen(tmp_path, agents=_continuous())
    drv = (tmp_path / "mem_driver.svh").read_text()
    init = drv.split("task initialize")[1].split("endtask")[0]
    assert "vif.gnt <= 1'd0;" in init
    assert "vif.rdata <= 32'd0;" in init
    assert "'1;" not in init  # never the hardcoded park


def test_responder_is_created_with_factory_context(tmp_path):
    """Without context, a per-instance factory override silently no-ops — so the
    'swap in an error-injecting responder' story would be a lie."""
    _gen(tmp_path)
    agt = (tmp_path / "mem_agent.svh").read_text()
    assert 'type_id::create(\n          "responder", null, get_full_name())' in agt


# --- liveness: a responder without an end-of-test check must be UNGENERATABLE ---


def test_responder_driver_always_has_a_liveness_check(tmp_path):
    """A dead responder is UNPROVABLE PER-TRANSACTION, so it must be proved at end-of-test.

    With no response the DUT never captures anything, so expected and actual are both zero
    and EVERY per-transaction compare agrees. This trap has reported TEST PASSED 34/34
    while the device was stone dead. The check is therefore GENERATED, outside any pragma
    — it must not depend on a human remembering to write it.

    Mutation-proved: memslave with a DUT that never asserts `req`, and its hand-written
    predictor check REMOVED, yields exactly 1 UVM_ERROR — DEAD_RESPONDER, from the
    generated driver. Before this, the same bench passed clean.
    """
    _gen(tmp_path)  # _BASE is a responder
    drv = (tmp_path / "mem_driver.svh").read_text()

    assert "function void check_phase" in drv
    assert "DEAD_RESPONDER" in drv
    assert "m_responses" in drv
    # ...and it must NOT be inside a pragma region, or a regeneration could drop it.
    body = drv.split("check_phase")[1]
    assert "pragma" not in body, "the liveness check must not live in a pragma region"


def test_continuous_responder_also_detects_a_silent_seam(tmp_path):
    """`m_responses > 0` is not enough: a responder whose response seam is EMPTY drives
    the idle value forever and looks perfectly alive."""
    _gen(tmp_path, agents=_continuous())
    drv = (tmp_path / "mem_driver.svh").read_text()
    assert "SILENT_RESPONDER" in drv
    assert "is_idle_response" in drv
    # the idle comparison must name every declared idle port
    assert "tr.gnt == 1'd0" in drv and "tr.rdata == 32'd0" in drv


def test_initiator_gets_no_liveness_check(tmp_path):
    """Opt-in: an initiator's driver must be byte-identical to before."""
    _gen(tmp_path, agents=_initiator())
    drv = (tmp_path / "mem_driver.svh").read_text()
    assert "DEAD_RESPONDER" not in drv
    assert "m_responses" not in drv
    assert "check_phase" not in drv


# --- F1: the response-timing contract (`respond:`) ---


def _zero_slack():
    a = {
        **_BASE["agents"][0],
        "idle": {"gnt": 0, "rdata": 0},
        "respond": "combinational",
    }
    return [a]


def test_respond_defaults_to_todays_contract(tmp_path):
    """Opt-in: absent `respond:` must reproduce the existing shape exactly."""
    cfg = _gen(tmp_path, agents=_continuous())
    a = cfg.agents[0]
    assert a.respond == "on_request"
    assert a.is_continuous and a.has_request_fifo and not a.is_zero_slack


def test_zero_slack_bypasses_the_sequencer_round_trip(tmp_path):
    """The DUT gives ONE cycle. The monitor -> fifo -> sequence -> sequencer -> driver
    chain costs at least one, so a zero-slack responder must not use it.

    Mutation-proved on examples/memslave_zs: `respond: combinational` passes 34/34;
    flip that ONE line to `on_request` and the same bench reports NO_PROGRESS with the
    DUT completing zero transfers. The responder is alive — it grants every request —
    it is just a cycle too late.
    """
    cfg = _gen(tmp_path, agents=_zero_slack())
    a = cfg.agents[0]
    assert a.is_zero_slack
    assert not a.has_request_fifo, (
        "a zero-slack responder cannot afford the fifo round-trip"
    )
    assert not a.is_continuous

    # no responder sequence at all — the driver IS the responder
    assert not (tmp_path / f"{a.responder_seq_name}.svh").exists()

    drv = (tmp_path / "mem_driver.svh").read_text()
    # raw signals, not the clocking block: cb1's output skew lands AFTER the edge the
    # DUT samples on, so a cb1 drive is always exactly one cycle late.
    assert "@(posedge vif.clk);" in drv
    assert "#1step;" in drv
    assert "vif.cb1.gnt" not in drv
    assert "seq_item_port.get_next_item" not in drv
    # ...and it must be live from time 0, or it misses the DUT's first request
    assert "wait (vif.rst_n" not in drv


def test_zero_slack_monitor_samples_request_and_response_together(tmp_path):
    """The request and the response happen in the SAME cycle, so they must land in the
    same snapshot. The default two-phase sample (inputs now, outputs one edge later)
    encodes the opposite assumption and pairs the grant with the wrong address."""
    _gen(tmp_path, agents=_zero_slack())
    assert "clocking mon_cb" in (tmp_path / "mem_if.sv").read_text()
    assert "@vif.mon_cb;" in (tmp_path / "mem_monitor.svh").read_text()


def test_zero_slack_still_gets_the_liveness_check(tmp_path):
    _gen(tmp_path, agents=_zero_slack())
    drv = (tmp_path / "mem_driver.svh").read_text()
    assert "DEAD_RESPONDER" in drv and "SILENT_RESPONDER" in drv
