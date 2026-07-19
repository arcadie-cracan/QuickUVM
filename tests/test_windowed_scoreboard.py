"""Windowed scoreboard (opt-in `window:` on a single-stream scoreboard).

A health-test / statistics block accumulates N samples and emits ONE verdict per
window (N:1). The generator carries the sample counter, the boundary keying off a
DUT strobe, the copy-through cadence, and the DUAL window-length liveness (a boundary
at the wrong count AND a window that never closes both fail); the user fills only the
domain accumulate + verdict seams. Proven end-to-end on examples/es_adaptp.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    AnalysisConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    ReferenceModelConfig,
    ScoreboardSpec,
    WindowSpec,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _es_agent():
    """A sample-stream agent: a driven `sample` input + a `window_done` boundary
    strobe and verdict outputs (what a health-test DUT exposes)."""
    return AgentConfig(
        name="es",
        interface="es_if",
        sequence_item="es_item",
        ports={
            "inputs": [PortConfig(name="sample", width=4)],
            "outputs": [
                PortConfig(name="window_done", width=1, randomize=False),
                PortConfig(name="ones_cnt", width=16, randomize=False),
                PortConfig(name="test_fail", width=1, randomize=False),
            ],
        },
    )


def _cfg(window=WindowSpec(boundary="window_done", length=8), monitor=None, lang="sv"):
    sb = ScoreboardSpec(
        reference_model=ReferenceModelConfig(language=lang),
        name="sb",
        source="es",
        monitor=monitor,
        window=window,
    )
    agents = [_es_agent()]
    if monitor is not None:
        agents.append(
            AgentConfig(
                name=monitor,
                interface=f"{monitor}_if",
                sequence_item=f"{monitor}_item",
                ports={"outputs": [PortConfig(name="v_out", width=8, randomize=False)]},
            )
        )
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="es_adaptp"),
        agents=agents,
        tests=[TConf(name="t1")],
        analysis=AnalysisConfig(scoreboards=[sb]),
    )


# ---- scaffold generation --------------------------------------------------


def test_windowed_scaffold_generated(tmp_path):
    Generator(_cfg()).generate_all(tmp_path)
    rm = (tmp_path / "es_adaptp_reference_model.svh").read_text()
    pr = (tmp_path / "es_adaptp_predictor.svh").read_text()
    # the feature's sample counter is a generated member
    assert "int m_wcount" in pr and "= 0;" in pr
    # boundary keyed off the named strobe; copy-through cadence
    assert "if (t.window_done) begin" in rm
    assert "extr.copy(t);" in rm
    # the two user seams
    assert "window_accumulate" in rm
    assert "window_verdict" in rm


def test_windowed_dual_liveness_generated(tmp_path):
    """Both halves of the liveness — a boundary at the wrong count AND a window that
    never closes — must be generated, so the DUT strobe is not a guard trusting itself."""
    rm = None
    Generator(_cfg()).generate_all(tmp_path)
    rm = (tmp_path / "es_adaptp_reference_model.svh").read_text()
    assert "if (m_wcount != 8)" in rm  # moved boundary (at the boundary)
    assert "if (m_wcount > 8)" in rm  # never-closing window (off the boundary)
    assert 'uvm_error("SB_WINDOW"' in rm


def test_unfilled_window_verdict_fatals(tmp_path):
    """An unfilled verdict seam must FATAL, not silently copy-through to a green bench."""
    Generator(_cfg()).generate_all(tmp_path)
    rm = (tmp_path / "es_adaptp_reference_model.svh").read_text()
    assert "UNFILLED_WINDOW" in rm


def test_zero_window_check_phase_guard(tmp_path):
    """A test that closes NO window (too short, or a stuck strobe) would slip past the
    boundary fatal — so the predictor's check_phase fails when m_windows == 0, and it
    counts a closed window at each boundary. Respects sb_enable (a disabled CSR test)."""
    Generator(_cfg()).generate_all(tmp_path)
    pr = (tmp_path / "es_adaptp_predictor.svh").read_text()
    rm = (tmp_path / "es_adaptp_reference_model.svh").read_text()
    assert "int m_windows = 0;" in pr
    assert "function void check_phase" in pr
    assert "m_enabled && m_windows == 0" in pr
    assert 'uvm_config_db#(bit)::get(this, "", "sb_enable", m_enabled)' in pr
    assert "m_windows++;" in rm  # counted at each boundary


def test_no_window_has_no_windowed_scaffold(tmp_path):
    """Without `window:` the plain predictor is generated (byte-identical elsewhere)."""
    Generator(_cfg(window=None)).generate_all(tmp_path)
    rm = (tmp_path / "es_adaptp_reference_model.svh").read_text()
    pr = (tmp_path / "es_adaptp_predictor.svh").read_text()
    assert "m_wcount" not in pr
    assert "SB_WINDOW" not in rm
    assert "window_accumulate" not in rm


# ---- validation -----------------------------------------------------------


def test_window_requires_single_stream():
    with pytest.raises(Exception, match="window requires a SINGLE-stream"):
        _cfg(monitor="mon")


def test_window_boundary_must_be_source_output():
    with pytest.raises(Exception, match="is not an output port"):
        _cfg(window=WindowSpec(boundary="nope", length=8))


def test_window_boundary_must_be_1bit():
    with pytest.raises(Exception, match="must be a 1-bit"):
        _cfg(window=WindowSpec(boundary="ones_cnt", length=8))  # ones_cnt is 16-bit


def test_window_length_must_be_positive():
    with pytest.raises(Exception, match="window length must be >= 1"):
        WindowSpec(boundary="window_done", length=0)


def test_window_requires_sv_reference_model():
    with pytest.raises(Exception, match="needs a SystemVerilog reference model"):
        _cfg(lang="c")
