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


def test_request_ready_emits_handshake_capture(tmp_path):
    """`request_ready` -> the monitor captures on the LEVEL of valid && ready (one publish
    per handshake cycle), not the rising edge. Real AXI HOLDS valid until ready, so
    back-to-back transfers under a held valid are distinct requests an edge-detect misses."""
    a = {**_BASE["agents"][0], "request_ready": "gnt"}
    _gen(tmp_path, agents=[a])
    mon = (tmp_path / "mem_monitor.svh").read_text()
    assert "if (tr.req && tr.gnt) request_ap.write(tr);" in mon
    assert "HANDSHAKE" in mon
    # no edge-detect state when capturing on the handshake
    assert "m_req_seen" not in mon


def test_request_ready_absent_keeps_edge_detect(tmp_path):
    """Opt-in: without `request_ready` the monitor is byte-identically the edge-detect."""
    _gen(tmp_path)  # _BASE has no request_ready
    mon = (tmp_path / "mem_monitor.svh").read_text()
    assert "if (tr.req && !m_req_seen) request_ap.write(tr);" in mon
    assert "HANDSHAKE" not in mon


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


def test_rejects_request_ready_on_an_initiator():
    a = _initiator(request_ready="gnt")
    with pytest.raises(ValidationError, match="only valid with"):
        ProjectConfig.model_validate({**_BASE, "agents": a})


def test_rejects_request_ready_unknown_port():
    a = {**_BASE["agents"][0], "request_ready": "nope"}
    with pytest.raises(ValidationError, match="must name a port the monitor samples"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_request_ready_too_wide():
    """request_ready is a 1-bit qualifier; `addr` is 8 bits."""
    a = {**_BASE["agents"][0], "request_ready": "addr"}
    with pytest.raises(ValidationError, match="must be 1 bit"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_request_ready_without_request_fifo():
    """request_ready only affects the request-publish, which prefetch/combinational lack —
    it would be a silent no-op there, so reject it fail-closed."""
    a = {**_BASE["agents"][0], "respond": "prefetch", "request_ready": "gnt"}
    with pytest.raises(ValidationError, match="needs `respond: on_request` or `pipelined`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_request_ready_equal_to_request_valid():
    """A handshake is valid AND ready — the same port for both is a degenerate self-AND."""
    a = {**_BASE["agents"][0], "request_ready": "req"}  # req is also request_valid
    with pytest.raises(ValidationError, match="must differ from"):
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


# --- F1c: `respond: prefetch` — the full-duplex shape ---


def _prefetch():
    a = {**_BASE["agents"][0], "respond": "prefetch"}
    return [a]


def test_prefetch_takes_its_item_before_the_transfer(tmp_path):
    """A full-duplex device drives its response on the SAME edge it samples the request,
    so the response cannot depend on the request it accompanies — the item must already
    be in hand. `get_next_item` therefore comes FIRST, before any wait.

    This is OpenTitan's spi_device_driver::get_and_drive(): get_next_item(req) first, and
    only THEN `wait (!csb)`.

    Mutation-proved on examples/spi_device: `prefetch` passes 177/177; `on_request` on the
    same bench gives 171 UVM_ERROR and DEAD_RESPONDER — the driver never gets an item in
    time to drive a single frame.
    """
    cfg = _gen(tmp_path, agents=_prefetch())
    a = cfg.agents[0]
    assert a.is_prefetch and a.has_responder_seq
    assert not a.has_request_fifo, "prefetch must not wait on the observed request"

    drv = (tmp_path / "mem_driver.svh").read_text()
    body = drv.split("task run_phase")[1]
    # the item must be fetched BEFORE the user's protocol seam runs
    assert body.index("get_next_item") < body.index("drive_transfer")


def test_prefetch_sequence_runs_ahead_of_the_bus(tmp_path):
    """The sequence must NOT block on the observed request — that is what makes the item
    available before the transfer starts."""
    _gen(tmp_path, agents=_prefetch())
    seq = (tmp_path / "mem_responder_seq.svh").read_text()
    assert "request_fifo.get" not in seq
    assert "prefetch_response" in seq


def test_prefetch_empty_seam_is_fatal_not_a_hang(tmp_path):
    """An unfilled protocol seam drove nothing, and the forever loop would then spin at
    the current timestep and HANG. A hung bench reports NOTHING — worse than a failing one.

    The guard must sit OUTSIDE the pragma: one placed inside the region it protects is
    deleted along with it. (It was, at first — and the empty seam hung for 5 minutes
    instead of failing.) A real transfer consumes time; a zero-time one drove nothing.
    """
    _gen(tmp_path, agents=_prefetch())
    drv = (tmp_path / "mem_driver.svh").read_text()
    assert "EMPTY_TRANSFER" in drv
    seam_start = drv.index("pragma quickuvm custom drive_transfer begin")
    seam_end = drv.index("pragma quickuvm custom drive_transfer end")
    assert not (seam_start < drv.index("EMPTY_TRANSFER") < seam_end), (
        "the guard is INSIDE the seam it guards — emptying the seam would delete it"
    )
    assert "$time == m_t0" in drv


def test_a_responder_on_a_dut_driven_clock_burns_no_edges_at_startup(tmp_path):
    """A DUT-driven clock is typically GATED — an SPI sck does not tick until the DUT opens
    a frame. The initiator's "wait 2 edges for the synchronizers to settle" would sleep
    through the start of the FIRST transfer and miss it (spi_device lost frame 0 to exactly
    this, and every later frame mismatched in cascade)."""
    cfg = ProjectConfig.model_validate(
        {
            **_BASE,
            "clock": [{"name": "clk"}, {"name": "sck", "source": "dut"}],
            "resets": [{"name": "rst_n", "active_low": True, "clock": "clk"}],
            "agents": [{**_BASE["agents"][0], "respond": "prefetch", "clock": "sck"}],
        }
    )
    Generator(cfg).generate_all(tmp_path, backup=False)
    init = (tmp_path / "mem_driver.svh").read_text().split("task initialize")[1]
    init = init.split("endtask")[0]
    assert "@vif.cb1" not in init, "a gated DUT clock may not have ticked yet"


def test_prefetch_counts_transfers_driven_not_items_fetched(tmp_path):
    """`m_responses` must mean "transfers I actually DROVE", not "items I fetched".

    A prefetch driver takes its item BEFORE waiting for the transfer to begin. If the
    counter is bumped at the fetch, then a driver parked forever inside `drive_transfer`
    — waiting on a frame the DUT never opens — has fetched an item but driven NOTHING,
    and reports itself alive. DEAD_RESPONDER goes blind to the exact failure it exists
    to catch.

    Proved on examples/spi_device with a DUT mutated never to assert csb: before the fix
    NO guard fired at all; after it, DEAD_RESPONDER does.
    """
    _gen(tmp_path, agents=_prefetch())
    body = (tmp_path / "mem_driver.svh").read_text().split("task run_phase")[1]
    fetch = body.index("get_next_item")
    seam = body.index("drive_transfer end")
    count = body.index("m_responses++")
    assert fetch < seam < count, (
        "m_responses++ must come AFTER the transfer completes — counting the fetch makes "
        "DEAD_RESPONDER blind to a driver that never drove anything"
    )


# --- F1d: `respond: pipelined` — multi-outstanding, out-of-order by ID (T6) ---


def _pipelined():
    """A responder that buffers N outstanding requests and answers out of order by an ID
    field (`id`), which must be a SAMPLED port."""
    a = {**_BASE["agents"][0], "respond": "pipelined", "reorder_by": "id"}
    a["ports"] = {
        "inputs": [
            {"name": "gnt", "width": 1, "randomize": True},
            {"name": "rdata", "width": 32, "randomize": True},
        ],
        "outputs": [
            {"name": "req", "width": 1},
            {"name": "addr", "width": 8},
            {"name": "id", "width": 4},
        ],
    }
    return [a]


def test_pipelined_predicates(tmp_path):
    """The pipelined shape has a responder sequence AND a request fifo (its accept thread
    drains that fifo), but is neither prefetch, zero-slack, nor continuous."""
    cfg = _gen(tmp_path, agents=_pipelined())
    a = cfg.agents[0]
    assert a.is_pipelined and a.has_responder_seq and a.has_request_fifo
    assert not (a.is_prefetch or a.is_zero_slack or a.is_continuous)


def test_pipelined_requires_reorder_by():
    a = {**_BASE["agents"][0], "respond": "pipelined"}
    with pytest.raises(ValidationError, match="requires `reorder_by`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_pipelined_reorder_by_must_be_sampled():
    """reorder_by names the request's ID field — a SAMPLED port (the DUT drives it)."""
    a = {**_pipelined()[0], "reorder_by": "gnt"}  # gnt is DRIVEN, not sampled
    with pytest.raises(ValidationError, match="must name a SAMPLED port"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_pipelined_reorder_by_is_not_the_valid_strobe():
    a = {**_pipelined()[0], "reorder_by": "req"}  # req is the request_valid qualifier
    with pytest.raises(ValidationError, match="cannot be the request_valid"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_reorder_by_rejected_without_pipelined():
    """reorder_by only means something for the pipelined shape."""
    a = {**_BASE["agents"][0], "reorder_by": "addr"}  # respond defaults to on_request
    with pytest.raises(ValidationError, match="only valid with `respond: pipelined`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_reorder_by_rejected_on_initiator():
    a = {**_BASE["agents"][0]}
    a.pop("mode")
    a.pop("request_valid")
    a["reorder_by"] = "addr"
    with pytest.raises(ValidationError, match="only valid with `mode: responder`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_pipelined_seq_decouples_accept_from_drive(tmp_path):
    """The whole point: the response loop must NOT be get -> respond -> get (which strands
    a burst). It is two forever threads — one buffers into per-ID queues, one drains them —
    and the drive thread does not block on a new request."""
    _gen(tmp_path, agents=_pipelined())
    seq = (tmp_path / "mem_responder_seq.svh").read_text()
    assert "fork" in seq and "id_q[int][$]" in seq
    assert "id_q[int'(in_req.id)].push_back" in seq  # buckets keyed by reorder_by
    assert "pop_front" in seq  # same-ID FIFO order
    # the seam is the SAME as on_request, so on_request<->pipelined preserves the fill
    assert "response_logic" in seq


def test_pipelined_has_a_strand_liveness_check(tmp_path):
    """DEAD_RESPONDER (in the driver) catches 'answered NOTHING'; it is blind to a STRAND
    (answered SOME, stranded the tail). The sequencer carries the complementary check:
    accepted must equal answered.

    Mutation-proved on examples/axi_read: break the drive loop to answer once and
    STRANDED_REQUESTS fires (accepted 5, answered 1); the correct drain passes 5/5.
    """
    _gen(tmp_path, agents=_pipelined())
    sqr = (tmp_path / "mem_sequencer.svh").read_text()
    assert "STRANDED_REQUESTS" in sqr
    assert "m_accepted" in sqr and "m_answered" in sqr
    assert "check_phase" in sqr


def test_pipelined_is_opt_in(tmp_path):
    """A responder without `respond: pipelined` gets none of the pipelined machinery."""
    _gen(tmp_path, agents=_continuous())
    sqr = (tmp_path / "mem_sequencer.svh").read_text()
    assert "STRANDED_REQUESTS" not in sqr and "m_accepted" not in sqr


# --- F1e: `reorder_policy` — the cross-ID arbitration knob (priority/round_robin/random) ---


def _pipelined_policy(policy):
    a = {**_pipelined()[0], "reorder_policy": policy}
    return [a]


def test_reorder_policy_defaults_to_priority(tmp_path):
    """Opt-in: absent `reorder_policy` reproduces the original lowest-id-first behaviour,
    byte-identical for a bench that never set it."""
    cfg = _gen(tmp_path, agents=_pipelined())
    assert cfg.agents[0].reorder_policy == "priority"
    seq = (tmp_path / "mem_responder_seq.svh").read_text()
    assert "reorder_policy: priority" in seq
    assert "m_last_id" not in seq and "urandom_range" not in seq


def test_reorder_policy_round_robin_emits_a_cursor(tmp_path):
    """Round-robin needs state (the id served last) that persists across responses, and it
    must wrap. Mutation-proved on examples/axi_reorder: round_robin gives the fully
    interleaved order [0 1 0 1 0 1] (same-id adjacency 0); flip to priority and it groups
    to [0 0 0 1 1 1] (adjacency 4), which the bench's $fatal catches."""
    cfg = _gen(tmp_path, agents=_pipelined_policy("round_robin"))
    assert cfg.agents[0].reorder_policy == "round_robin"
    seq = (tmp_path / "mem_responder_seq.svh").read_text()
    # The cursor MUST start below every legal id (-1) so the first pick is the lowest ready
    # id. Starting at 0 would skip id 0 on a full first backlog — a regression the example's
    # adjacency check cannot see (both orders have adjacency 0), so pin the init value here.
    assert "int m_last_id = -1;" in seq
    assert "ready[i] > m_last_id" in seq  # next id ABOVE the cursor
    assert "wrap to the lowest ready id" in seq  # ...else wrap
    assert "urandom_range" not in seq


def test_reorder_policy_random_emits_urandom(tmp_path):
    cfg = _gen(tmp_path, agents=_pipelined_policy("random"))
    assert cfg.agents[0].reorder_policy == "random"
    seq = (tmp_path / "mem_responder_seq.svh").read_text()
    assert "$urandom_range(0, ready.size() - 1)" in seq
    assert "m_last_id" not in seq


def test_reorder_policy_rejected_without_pipelined():
    """The knob is meaningless without the pipelined shape (on_request has no per-id pick)."""
    a = {
        **_BASE["agents"][0],
        "reorder_policy": "round_robin",
    }  # respond defaults on_request
    with pytest.raises(ValidationError, match="only valid with `respond: pipelined`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_reorder_policy_rejected_on_initiator():
    a = {**_BASE["agents"][0]}
    a.pop("mode")
    a.pop("request_valid")
    a["reorder_policy"] = "random"
    with pytest.raises(ValidationError, match="only valid with"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_reorder_policy_rejected_on_other_responder_shapes():
    """The same guard governs prefetch and combinational responders (not just on_request):
    none of them has a per-id pick, so a non-default policy is meaningless there too."""
    for shape in ("prefetch", "combinational"):
        a = {**_BASE["agents"][0], "respond": shape, "reorder_policy": "round_robin"}
        with pytest.raises(
            ValidationError, match="only valid with `respond: pipelined`"
        ):
            ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_reorder_policy_rejects_unknown_value():
    a = {**_pipelined()[0], "reorder_policy": "fifo"}
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_reorder_by_width_capped_for_the_pick():
    """The pick keys buckets with int'(<id>) and seeds the round-robin cursor at -1; a
    >= 32-bit id could cast negative and alias the sentinel, so the width is capped."""
    a = {**_pipelined()[0]}
    a["ports"] = {
        "inputs": [{"name": "gnt", "width": 1}, {"name": "rdata", "width": 32}],
        "outputs": [{"name": "req", "width": 1}, {"name": "id", "width": 32}],
    }
    with pytest.raises(ValidationError, match="too wide for the per-ID pick"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_reorder_policy_priority_is_byte_identical_to_the_default(tmp_path):
    """Setting reorder_policy: priority explicitly must generate exactly what the default
    (unset) does — the pick code is the same, only the comment names the policy."""
    d1 = tmp_path / "default"
    d2 = tmp_path / "explicit"
    _gen(d1, agents=_pipelined())
    _gen(d2, agents=_pipelined_policy("priority"))
    assert (d1 / "mem_responder_seq.svh").read_text() == (
        d2 / "mem_responder_seq.svh"
    ).read_text()
