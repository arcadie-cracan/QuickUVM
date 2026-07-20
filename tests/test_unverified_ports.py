"""dut.unverified_ports — a port-coverage waiver: DUT ports deliberately out of
verification scope.

The generator never sees the RTL, so the names are not checked against it; the
walls guard the contradictions the schema CAN see (a waived port an agent
connects, the bench clock/reset). The waiver renders as a comment above
dut_inst so the intent survives into the bench; absence renders nothing
(byte-identity over the corpus is the no-change proof)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig


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


def _with_waiver(*ports):
    c = _cfg()
    c["dut"]["unverified_ports"] = list(ports)
    return c


# --- walls --------------------------------------------------------------------


def test_bad_identifier_rejected():
    with pytest.raises(ValidationError, match="not a legal SystemVerilog identifier"):
        ProjectConfig.model_validate(_with_waiver("2scan"))


def test_duplicates_rejected():
    with pytest.raises(ValidationError, match="duplicate entries"):
        ProjectConfig.model_validate(_with_waiver("scan_en", "scan_en"))


def test_agent_connected_port_rejected():
    """A port cannot be both verified (agent-connected) and waived."""
    with pytest.raises(ValidationError, match="connected by agent 'm'"):
        ProjectConfig.model_validate(_with_waiver("din"))


def test_clock_rejected():
    with pytest.raises(ValidationError, match="bench clock/reset net"):
        ProjectConfig.model_validate(_with_waiver("clk"))


def test_reset_rejected():
    with pytest.raises(ValidationError, match="bench clock/reset net"):
        ProjectConfig.model_validate(_with_waiver("rst_n"))


# --- accepted + rendered ------------------------------------------------------


def test_waiver_renders_comment_above_dut_inst(tmp_path: Path):
    cfg = ProjectConfig.model_validate(_with_waiver("scan_en", "test_mode"))
    Generator(cfg).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "Deliberately UNVERIFIED DUT ports" in top
    assert "scan_en, test_mode" in top


def test_no_waiver_renders_nothing(tmp_path: Path):
    cfg = ProjectConfig.model_validate(_cfg())
    Generator(cfg).generate_all(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "UNVERIFIED" not in top


def test_round_trips_through_model_dump():
    cfg = ProjectConfig.model_validate(_with_waiver("scan_en"))
    again = ProjectConfig.model_validate(cfg.model_dump())
    assert again.dut.unverified_ports == ["scan_en"]
