"""F2 — a clock the TB OBSERVES but never drives (`clock[].source: dut`).

A device agent's clock is a DUT OUTPUT: an SPI `sck`, an I2C `scl`. Every QuickUVM clock
used to come from a generated `clkgen`, so there was no way to say so — and the way people
"fix" the resulting `*E,MULDRN` is to delete the port from the `dut_connections` pragma,
which elaborates CLEAN and keys the whole bench to a TB-invented PHANTOM clock. It runs, it
passes, and it measures nothing. These tests exist to keep that unreachable.
"""

import pytest
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.merger import MergeError
from quick_uvm.models import ProjectConfig

_BASE = {
    "project": {"name": "spidev_tb", "author": "a@b.c"},
    "dut": {
        "name": "spi_host",
        "clock": "clk",
        "reset": "rst_n",
        "external_reset": True,
    },
    "clock": [
        {"name": "clk", "period": 10, "unit": "ns"},
        {"name": "sck", "period": 40, "unit": "ns", "source": "dut"},
    ],
    "resets": [{"name": "rst_n", "active_low": True, "clock": "clk"}],
    "agents": [
        {
            "name": "spi",
            "interface": "spi_if",
            "sequence_item": "spi_item",
            "clock": "sck",
            "reset": "rst_n",
            "ports": {
                "inputs": [{"name": "miso", "width": 1}],
                "outputs": [{"name": "csb", "width": 1}, {"name": "mosi", "width": 1}],
            },
        }
    ],
    "tests": [{"name": "rand_test"}],
}


def _gen(tmp_path, **over):
    cfg = ProjectConfig.model_validate({**_BASE, **over})
    Generator(cfg).generate_all(tmp_path, backup=False)
    return cfg


def test_observed_clock_gets_no_clkgen(tmp_path):
    """A clkgen on a DUT output is a SECOND DRIVER — Xcelium rejects it (*E,MULDRN)."""
    _gen(tmp_path)
    top = (tmp_path / "tb_top.sv").read_text()
    assert "clkgen #(10) ck_clk (clk);" in top  # the TB clock still gets one
    assert "ck_sck" not in top  # ...the observed one must NOT
    assert "wire  sck;" in top  # it is a net the DUT drives
    assert "logic sck;" not in top


def test_default_source_is_tb(tmp_path):
    cfg = ProjectConfig.model_validate(_BASE)
    clk = next(c for c in cfg.effective_clocks if c.name == "clk")
    assert clk.source == "tb" and not clk.observed
    assert [c.name for c in cfg.observed_clocks] == ["sck"]


# --- the phantom clock must be UNREACHABLE, not merely documented ---


def _delete_connection(tmp_path, port):
    import re

    p = tmp_path / "tb_top.sv"
    p.write_text(re.sub(rf"\n\s*\.{port}\({port}\),?", "", p.read_text()))


def test_refuses_an_observed_clock_with_no_driver(tmp_path):
    """`source: dut` means the DUT is the clock's ONLY driver. Unconnected, nothing
    drives it — the bench elaborates, runs, and measures nothing."""
    cfg = ProjectConfig.model_validate(_BASE)
    Generator(cfg).generate_all(tmp_path, backup=False)
    _delete_connection(tmp_path, "sck")
    with pytest.raises(MergeError, match="not connected to the DUT"):
        Generator(cfg).generate_all(tmp_path, backup=False)


def test_refuses_a_phantom_tb_clock(tmp_path):
    """THE ORIGINAL TRAP. Declare a clock the DUT OUTPUTS as a normal TB clock, hit
    *E,MULDRN (the clkgen fights the DUT's driver), and "fix" it by deleting the port
    from the dut_connections pragma. Elaboration goes clean — on a phantom clock.

    The refusal must name the real fix (`source: dut`), not just complain.
    """
    d = {**_BASE, "clock": [{"name": "clk"}, {"name": "sck", "period": 40}]}
    cfg = ProjectConfig.model_validate(d)
    Generator(cfg).generate_all(tmp_path, backup=False)
    _delete_connection(tmp_path, "sck")
    with pytest.raises(MergeError, match="PHANTOM clock"):
        Generator(cfg).generate_all(tmp_path, backup=False)
    try:
        Generator(cfg).generate_all(tmp_path, backup=False)
    except MergeError as e:
        assert "source: dut" in str(e), (
            "the error must name the fix, not just the fault"
        )


def test_combinational_dut_is_exempt(tmp_path):
    """A combinational DUT has no clock port at all — nothing to connect, nothing to be
    a phantom of. Without this exemption the check aborts 18 of the committed examples."""
    cfg = ProjectConfig.model_validate(
        {
            "project": {"name": "c_tb", "author": "a@b.c"},
            "dut": {"name": "c", "clock": "clk", "reset": "", "combinational": True},
            "agents": [
                {
                    "name": "io",
                    "interface": "io_if",
                    "sequence_item": "io_item",
                    "ports": {
                        "inputs": [{"name": "a", "width": 8}],
                        "outputs": [{"name": "y", "width": 8}],
                    },
                }
            ],
            "tests": [{"name": "rand_test"}],
        }
    )
    Generator(cfg).generate_all(tmp_path, backup=False)  # must not raise


# --- fail-closed schema rules ---


def test_rejects_an_all_observed_clock_set():
    """A test's run length is measured in TB clock edges. With none, a DUT that never
    toggles its clock would HANG rather than fail — and a hung bench reports nothing."""
    d = {**_BASE, "clock": [{"name": "sck", "source": "dut"}]}
    with pytest.raises(ValidationError, match="TB generates no clock"):
        ProjectConfig.model_validate(d)


def test_rejects_observing_the_duts_own_clock_input():
    d = {
        **_BASE,
        "clock": [{"name": "clk", "source": "dut"}, {"name": "sck"}],
    }
    with pytest.raises(ValidationError, match="CLOCK INPUT"):
        ProjectConfig.model_validate(d)


def test_rejects_a_reset_synced_to_an_observed_clock():
    """The DUT only starts driving sck once it is OUT of reset. Deasserting reset
    synchronously to sck is a deadlock."""
    d = {**_BASE, "resets": [{"name": "rst_n", "active_low": True, "clock": "sck"}]}
    with pytest.raises(ValidationError, match="deadlock"):
        ProjectConfig.model_validate(d)
