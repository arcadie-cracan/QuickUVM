"""Value-sanity walls (schema-philosophy-audit, PR 3).

Small fail-closed guards for configs that validated and then produced a hung,
mis-timed, or vacuous bench:

* clock.period <= 0 generated `forever #0 clk = ~clk` — hangs at t=0, and a
  hung bench can never report an error;
* an unknown clock unit KeyError'd deep in the multi-clock math (or silently
  passed through to templates single-clock);
* drive_offset_pct outside 0..99 drove outside the clock period;
* negative num_items generated a zero-iteration repeat (runs nothing, passes);
  0 stays legal — the committed pragma-driven idiom (examples/spi_host);
* `respond:` on an initiator was the ONE responder-only knob accepted silently
  (its six siblings were already rejected);
* idle + respond:prefetch generated a bench whose per-cycle liveness could
  never be satisfied (prefetch has no per-cycle drive loop);
* under `resets:`, a dut.reset outside the declared domains was silently
  ignored — it must now name one of them (external_reset stays unconstrained:
  the multi path top-drives every domain regardless, and the corpus carries
  both spellings).
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


# --- clock numeric sanity -----------------------------------------------------


@pytest.mark.parametrize("period", [0, -10])
def test_clock_period_must_be_positive(period):
    with pytest.raises(ValidationError, match="period must be >= 1"):
        ProjectConfig.model_validate(_cfg(clock={"period": period, "unit": "ns"}))


def test_clock_unknown_unit_rejected():
    with pytest.raises(ValidationError, match="unknown unit"):
        ProjectConfig.model_validate(_cfg(clock={"period": 10, "unit": "nanoseconds"}))


@pytest.mark.parametrize("pct", [-20, 100, 150])
def test_drive_offset_pct_bounded(pct):
    with pytest.raises(ValidationError, match="drive_offset_pct"):
        ProjectConfig.model_validate(
            _cfg(clock={"period": 10, "unit": "ns", "drive_offset_pct": pct})
        )


# --- num_items ---------------------------------------------------------------


def test_negative_num_items_rejected():
    with pytest.raises(ValidationError, match="num_items must be >= 0"):
        ProjectConfig.model_validate(_cfg(tests=[{"name": "t1", "num_items": -5}]))


def test_zero_num_items_stays_legal():
    """The committed pragma-driven idiom (examples/spi_host)."""
    ProjectConfig.model_validate(_cfg(tests=[{"name": "t1", "num_items": 0}]))


# --- respond: on an initiator -------------------------------------------------


@pytest.mark.parametrize("shape", ["prefetch", "combinational", "pipelined"])
def test_respond_rejected_on_initiator(shape):
    agent = {
        "name": "m",
        "interface": "m_if",
        "sequence_item": "m_item",
        "respond": shape,
        "ports": {
            "inputs": [{"name": "din", "width": 8}],
            "outputs": [{"name": "dout", "width": 8}],
        },
    }
    with pytest.raises(ValidationError, match="only valid.*mode: responder"):
        ProjectConfig.model_validate(_cfg(agents=[agent]))


# --- idle x prefetch ----------------------------------------------------------


def test_idle_with_prefetch_rejected():
    agent = {
        "name": "mem",
        "interface": "mem_if",
        "sequence_item": "mem_item",
        "mode": "responder",
        "request_valid": "req",
        "respond": "prefetch",
        "idle": {"gnt": 0},
        "ports": _RESP_PORTS,
    }
    with pytest.raises(ValidationError, match="incompatible with `respond: prefetch"):
        ProjectConfig.model_validate(_cfg(agents=[agent]))


def test_idle_with_combinational_stays_legal():
    """The committed zero-slack shape (examples/memslave_zs)."""
    agent = {
        "name": "mem",
        "interface": "mem_if",
        "sequence_item": "mem_item",
        "mode": "responder",
        "request_valid": "req",
        "respond": "combinational",
        "idle": {"gnt": 0},
        "ports": _RESP_PORTS,
    }
    ProjectConfig.model_validate(_cfg(agents=[agent]))


# --- resets: consistency ------------------------------------------------------

_TWO_RESETS = [
    {"name": "rst_a", "active_low": True},
    {"name": "rst_b", "active_low": True},
]


def test_resets_requires_dut_reset_among_domains():
    cfg = _cfg(
        dut={
            "name": "d",
            "clock": "clk",
            "reset": "rst_n",  # not a declared domain
        },
        reset=_TWO_RESETS,
    )
    with pytest.raises(ValidationError, match="not one of the declared"):
        ProjectConfig.model_validate(cfg)


def test_resets_consistent_config_passes():
    """dut.reset naming a declared domain passes (under the reset: LIST the
    multi path top-drives every domain; the scalar external knob is the
    single-reset spelling and cannot co-exist with the list)."""
    cfg = _cfg(
        dut={"name": "d", "clock": "clk", "reset": "rst_a"},
        reset=_TWO_RESETS,
    )
    ProjectConfig.model_validate(cfg)


# --- the reset: union (symmetry with clock:) ---------------------------------


def test_reset_scalar_maps_to_internal_fields():
    cfg = _cfg(reset={"active_low": False, "external": True})
    c = ProjectConfig.model_validate(cfg)
    assert c.dut.reset_active_low is False
    assert c.dut.external_reset is True


def test_reset_list_is_the_multi_reset_form():
    cfg = _cfg(
        dut={"name": "d", "clock": "clk", "reset": "rst_a"},
        reset=_TWO_RESETS,
    )
    c = ProjectConfig.model_validate(cfg)
    assert [r.name for r in c.effective_resets] == ["rst_a", "rst_b"]


def test_old_dut_reset_knobs_error_with_move_hint():
    for key in ("external_reset", "reset_active_low"):
        cfg = _cfg(dut={"name": "d", "clock": "clk", "reset": "rst_n", key: True})
        with pytest.raises(ValidationError, match="moved to the top-level `reset:`"):
            ProjectConfig.model_validate(cfg)


def test_old_resets_key_errors_with_move_hint():
    cfg = _cfg(resets=_TWO_RESETS)
    with pytest.raises(ValidationError, match="`reset:` key"):
        ProjectConfig.model_validate(cfg)


def test_reset_scalar_rejects_unknown_keys():
    cfg = _cfg(reset={"name": "rst_n", "external": True})
    with pytest.raises(ValidationError, match="accepts"):
        ProjectConfig.model_validate(cfg)


def test_reset_union_round_trips_through_model_dump():
    c = ProjectConfig.model_validate(_cfg(reset={"external": True}))
    reloaded = ProjectConfig.model_validate(c.model_dump())
    assert reloaded.dut.external_reset is True
