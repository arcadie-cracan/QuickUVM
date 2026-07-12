"""Bidirectional (`inouts`) ports — a shared wire the DUT and the TB both drive.

Neither `inputs` (TB-driven) nor `outputs` (DUT-driven) can express a net that must be
RELEASED, so `inouts` is a third category — the direction keyword, completing
inputs/outputs/inouts <-> input/output/inout.

Most of the tests below exist because the naive implementation SILENTLY PASSED: the
resolved line was predicted but never compared, so a DUT that broke open-drain entirely
still reported 62/62. Every assertion here corresponds to a bug that was real.
"""

import pytest
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_BASE = {
    "project": {"name": "od_tb", "author": "a@b.c"},
    "dut": {"name": "od", "clock": "clk", "reset": "rst_n", "external_reset": True},
    "agents": [
        {
            "name": "bus",
            "interface": "bus_if",
            "sequence_item": "bus_item",
            "ports": {
                "outputs": [{"name": "dut_low", "width": 1}],
                "inouts": [
                    {"name": "sda", "width": 1, "open_drain": True, "pullup": True}
                ],
            },
        }
    ],
    "tests": [{"name": "rand_test"}],
}


def _gen(tmp_path, **over):
    cfg = ProjectConfig.model_validate({**_BASE, **over})
    Generator(cfg).generate_all(tmp_path, backup=False)
    return cfg


def _no_inouts():
    a = {**_BASE["agents"][0]}
    a["ports"] = {
        "inputs": [{"name": "a", "width": 8, "randomize": True}],
        "outputs": [{"name": "dut_low", "width": 1}],
    }
    return [a]


# --- opt-in / byte-identity -------------------------------------------------


def test_no_inouts_emits_nothing_new(tmp_path):
    _gen(tmp_path, agents=_no_inouts())
    iface = (tmp_path / "bus_if.sv").read_text()
    assert "wire" not in iface
    assert "_oe" not in iface
    trans = (tmp_path / "bus_item.svh").read_text()
    assert "_oe" not in trans


# --- the electrical contract ------------------------------------------------


def test_open_drain_resolution_and_pullup(tmp_path):
    """The line is a `wire` (resolved from both sides); the TB can only pull LOW or
    RELEASE; and a pullup makes the released line read 1 rather than float to X."""
    _gen(tmp_path)
    iface = (tmp_path / "bus_if.sv").read_text()
    assert "wire  sda;" in iface
    # open-drain: driving a 1 IS releasing — the line can never be driven high
    assert "assign sda = (sda_oe && !sda_o) ? 1'b0 : 1'bz;" in iface
    # NOT a `pullup` primitive: primitives are illegal inside an interface (*E,INFINS)
    assert "assign (weak1, weak0) sda = '1;" in iface
    assert "pullup (" not in iface


def test_plain_tristate_drives_both_levels(tmp_path):
    """Without open_drain, a tri-state bus drives high AND low; it just releases on !oe."""
    a = {**_BASE["agents"][0]}
    a["ports"] = {
        "outputs": [{"name": "dut_low", "width": 1}],
        "inouts": [{"name": "d", "width": 8}],
    }
    _gen(tmp_path, agents=[a])
    iface = (tmp_path / "bus_if.sv").read_text()
    assert "assign d = d_oe ? d_o : 8'bz;" in iface


def test_dut_declares_inout_wire_and_top_connects_it(tmp_path):
    """The DUT was originally left UNCONNECTED — the TB and DUT sat on different wires and
    the scoreboard compared a line the DUT could not reach."""
    _gen(tmp_path)
    dut = (tmp_path / "od.sv").read_text()
    assert "inout  wire  sda," in dut
    top = (tmp_path / "tb_top.sv").read_text()
    assert ".sda(bus_if_inst.sda)," in top


# --- the transaction contract (each of these was a silent-pass bug) ----------


def test_transaction_has_all_three_fields(tmp_path):
    _gen(tmp_path)
    trans = (tmp_path / "bus_item.svh").read_text()
    assert "rand bit sda_o;" in trans
    assert "rand bit sda_oe;" in trans
    assert "logic sda;" in trans


def _macros():
    a = {**_BASE["agents"][0], "seq_item_style": "field_macros"}
    return [a]


def test_do_compare_compares_the_resolved_line(tmp_path):
    """THE bug that made the whole feature a no-op: the resolved line was predicted and
    then never compared, so a DUT that broke open-drain entirely still passed 62/62.

    `<n>_o`/`<n>_oe` are NOT compared — they are what WE drove, so comparing them would
    only prove we drove what we drove.
    """
    _gen(tmp_path)  # `manual` is the default style
    trans = (tmp_path / "bus_item.svh").read_text()
    # NB "do_compare" also appears in the fatal message, so anchor on the signature
    cmp_body = trans.split("function bit do_compare")[1].split("endfunction")[0]
    assert "sda === tr.sda" in cmp_body
    assert "sda_o ===" not in cmp_body
    assert "sda_oe ===" not in cmp_body


def test_field_macro_style_compares_the_line_not_the_drive_state(tmp_path):
    """The other transaction style has its own compare mechanism, and the same trap: the
    resolved line must be UVM_ALL_ON (compared), the drive state UVM_NOCOMPARE."""
    _gen(tmp_path, agents=_macros())
    trans = (tmp_path / "bus_item.svh").read_text()
    assert "`uvm_field_int(sda,    UVM_ALL_ON)" in trans
    assert "`uvm_field_int(sda_o,  UVM_ALL_ON | UVM_NOCOMPARE)" in trans
    assert "`uvm_field_int(sda_oe, UVM_ALL_ON | UVM_NOCOMPARE)" in trans


def test_do_copy_copies_the_drive_state(tmp_path):
    """Without this the predictor loses `_o`/`_oe` and models a bus nobody was driving."""
    _gen(tmp_path)  # `manual` is the default style
    trans = (tmp_path / "bus_item.svh").read_text()
    copy_body = trans.split("function void do_copy")[1].split("endfunction")[0]
    # the generated code is column-aligned, so normalise whitespace before matching
    flat = " ".join(copy_body.split())
    for f in ("sda", "sda_o", "sda_oe"):
        assert f"{f} = tr.{f};" in flat


def test_monitor_samples_the_line_with_the_outputs(tmp_path):
    """A shared line and BOTH drivers' states must be observed at the SAME INSTANT, or a
    model of the resolution compares the line from one cycle against a driver's state from
    the next. Sampling the inouts with the TB-driven inputs was off by a cycle."""
    _gen(tmp_path)
    mon = (tmp_path / "bus_monitor.svh").read_text()
    # the resolved line comes through the clocking block, with the DUT outputs
    assert "t.sda    = vif.cb1.sda;" in mon
    out_section = mon.split("Sample DUT outputs")[1]
    assert "t.sda" in out_section


def test_driver_releases_every_line_at_time_zero(tmp_path):
    """A TB that drives a shared line before it has anything to say fights the DUT and
    both ends read X."""
    _gen(tmp_path)
    drv = (tmp_path / "bus_driver.svh").read_text()
    init = drv.split("task initialize")[1].split("endtask")[0]
    assert "vif.sda_oe <= 1'b0;" in init


def test_coverage_may_target_the_synthesised_fields(tmp_path):
    """`<n>_oe` (who is holding the line?) is usually the most interesting coverpoint on a
    shared bus — refusing to cover it would make the feature half-useless."""
    cfg = _gen(
        tmp_path,
        analysis={"coverage": ["bus"]},
        coverage_models=[
            {
                "agent": "bus",
                "coverpoints": [
                    {
                        "field": "sda_oe",
                        "bins": [
                            {"name": "released", "value": 0},
                            {"name": "driving", "value": 1},
                        ],
                    }
                ],
            }
        ],
    )
    assert "sda_oe" in cfg.agents[0].coverable_fields
    cov = (tmp_path / "bus_cov.svh").read_text()
    assert "sda_oe" in cov


# --- fail-closed validation -------------------------------------------------


def test_open_drain_requires_a_pullup():
    """Not a style preference: with no pullup the line floats to X the moment everyone
    releases, and every sample downstream is poisoned."""
    a = {**_BASE["agents"][0]}
    a["ports"] = {"inouts": [{"name": "sda", "width": 1, "open_drain": True}]}
    with pytest.raises(ValidationError, match="needs `pullup: true`"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_open_drain_must_be_one_bit():
    a = {**_BASE["agents"][0]}
    a["ports"] = {
        "inouts": [{"name": "b", "width": 8, "open_drain": True, "pullup": True}]
    }
    with pytest.raises(ValidationError, match="must be 1 bit"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_a_name_in_both_inputs_and_inouts():
    a = {**_BASE["agents"][0]}
    a["ports"] = {
        "inputs": [{"name": "sda", "width": 1}],
        "inouts": [{"name": "sda", "width": 1, "open_drain": True, "pullup": True}],
    }
    with pytest.raises(ValidationError, match="also appears in inputs/outputs"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})


def test_rejects_a_port_colliding_with_a_synthesised_field():
    """An inout `sda` generates `sda_o`/`sda_oe`; a declared port of that name collides."""
    a = {**_BASE["agents"][0]}
    a["ports"] = {
        "inputs": [{"name": "sda_oe", "width": 1}],
        "inouts": [{"name": "sda", "width": 1, "open_drain": True, "pullup": True}],
    }
    with pytest.raises(ValidationError, match="collides with a declared port"):
        ProjectConfig.model_validate({**_BASE, "agents": [a]})
