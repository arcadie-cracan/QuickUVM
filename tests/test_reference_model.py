"""K0 — reference-model language: SV (default) vs DPI-C bridge + C stub.

`reference_model.language: c` generates a fully-generated SV marshaling bridge
(`import "DPI-C" function void <dut>_predict(...)` + predict() that copies the
transaction, calls the C function, and unpacks the expected outputs) plus a
`<dut>_reference_model.c` stub whose signature is derived from the primary
agent's fields. Default `sv` is byte-identical (the SV predict() body).
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
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _agent(inputs, outputs, name="a"):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        ports={"inputs": inputs, "outputs": outputs},
    )


def _cfg(language="c", inputs=None, outputs=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[
            _agent(
                inputs or [PortConfig(name="x", width=8)],
                outputs or [PortConfig(name="y", width=8)],
            )
        ],
        tests=[TConf(name="t1")],
        # the knob lives ON the scoreboard it configures (the sole flat set)
        analysis=AnalysisConfig(
            coverage=["a"],
            scoreboards=[
                ScoreboardSpec(
                    name="sbd",
                    source="a",
                    reference_model=ReferenceModelConfig(language=language),
                )
            ],
        ),
    )


def _gen(tmp_path, **kw):
    Generator(_cfg(**kw)).generate_all(tmp_path)
    return tmp_path


# ---- DPI type mapping ------------------------------------------------------


def test_dpi_type_properties():
    assert PortConfig(name="p", width=1).dpi_sv_type == "byte"
    assert PortConfig(name="p", width=8).dpi_sv_type == "byte"
    assert PortConfig(name="p", width=12).dpi_sv_type == "shortint"
    assert PortConfig(name="p", width=32).dpi_sv_type == "int"
    assert PortConfig(name="p", width=64).dpi_sv_type == "longint"
    assert PortConfig(name="p", width=8).dpi_c_type == "char"
    assert PortConfig(name="p", width=16).dpi_c_type == "short"
    assert PortConfig(name="p", width=32).dpi_c_type == "int"
    assert PortConfig(name="p", width=64).dpi_c_type == "long long"


# ---- default sv path -------------------------------------------------------


def test_default_sv_no_c_file(tmp_path):
    _gen(tmp_path, language="sv")
    svh = (tmp_path / "d_reference_model.svh").read_text()
    assert "prediction_logic" in svh  # the SV golden-model pragma
    assert 'import "DPI-C"' not in svh
    assert not (tmp_path / "d_reference_model.c").exists()


# ---- DPI-C path ------------------------------------------------------------


def test_c_generates_bridge_and_stub(tmp_path):
    _gen(tmp_path, language="c")
    svh = (tmp_path / "d_reference_model.svh").read_text()
    assert 'import "DPI-C" function void d_predict(' in svh
    assert (tmp_path / "d_reference_model.c").exists()


def test_dpi_signature_types(tmp_path):
    _gen(
        tmp_path,
        language="c",
        inputs=[PortConfig(name="a", width=8), PortConfig(name="b", width=20)],
        outputs=[PortConfig(name="r", width=64)],
    )
    svh = (tmp_path / "d_reference_model.svh").read_text()
    assert "input byte a" in svh
    assert "input int b" in svh  # 20 bits -> int
    assert "output longint r" in svh
    c = (tmp_path / "d_reference_model.c").read_text()
    assert "char a" in c
    assert "int b" in c
    assert "long long *r" in c  # output by pointer


def test_bridge_marshals_transaction(tmp_path):
    _gen(
        tmp_path,
        language="c",
        inputs=[PortConfig(name="a", width=8)],
        outputs=[PortConfig(name="r", width=8)],
    )
    svh = (tmp_path / "d_reference_model.svh").read_text()
    assert "function add_seq_item" not in svh  # uses the agent's seq_item (a_seq_item)
    assert "extr.copy(t);" in svh
    assert "d_predict(" in svh
    assert "extr.r = r;" in svh  # output unpacked into the expected transaction


def test_c_stub_has_pragma(tmp_path):
    _gen(tmp_path, language="c")
    c = (tmp_path / "d_reference_model.c").read_text()
    assert "// pragma quickuvm custom reference_model begin" in c
    assert "// pragma quickuvm custom reference_model end" in c
    assert '#include "svdpi.h"' in c


def test_run_f_lists_c_file(tmp_path):
    _gen(tmp_path, language="c")
    runf = (tmp_path / "run.f").read_text()
    assert "d_reference_model.c" in runf


def test_enum_input_is_cast_in_bridge(tmp_path):
    _gen(
        tmp_path,
        language="c",
        inputs=[PortConfig(name="op", width=4, enum={"ADD": 0, "SUB": 1})],
        outputs=[PortConfig(name="r", width=8)],
    )
    svh = (tmp_path / "d_reference_model.svh").read_text()
    assert "byte'(t.op)" in svh  # enum cast to the DPI scalar type


# ---- validation ------------------------------------------------------------


def test_width_over_64_rejected():
    with pytest.raises(Exception, match="≤64-bit|<=64|64-bit"):
        _cfg(
            language="c",
            inputs=[PortConfig(name="wide", width=65)],
            outputs=[PortConfig(name="r", width=8)],
        )


def test_wide_field_ok_when_sv():
    # the >64-bit restriction only applies to the DPI-C path
    _cfg(
        language="sv",
        inputs=[PortConfig(name="wide", width=128)],
        outputs=[PortConfig(name="r", width=8)],
    )


# ---- the per-scoreboard placement (the analysis unification, part 2) --------


def test_top_level_reference_model_key_errors_with_move_hint():
    with pytest.raises(Exception, match="moved ONTO the scoreboard"):
        ProjectConfig.model_validate(
            {
                "project": {"name": "t"},
                "dut": {"name": "d", "reset": "", "combinational": True},
                "agents": [
                    {
                        "name": "a",
                        "interface": "a_if",
                        "sequence_item": "a_item",
                        "ports": {"inputs": [{"name": "x", "width": 8}]},
                    }
                ],
                "reference_model": {"language": "c"},
                "tests": [{"name": "t1"}],
            }
        )


def test_effective_reference_model_routes_from_the_sole_scoreboard():
    cfg = _cfg(language="c")
    assert cfg.reference_model.language == "c"
    # implicit scoreboard (no analysis block) -> the default SV seam
    bare = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[
            _agent([PortConfig(name="x", width=8)], [PortConfig(name="y", width=8)])
        ],
        tests=[TConf(name="t1")],
    )
    assert bare.reference_model.language == "sv"


def test_dpi_c_requires_the_sole_scoreboard():
    """multi-scoreboard benches emit one SV predict() per set — `c` on any entry
    would be silently ignored, so it is rejected fail-closed."""
    with pytest.raises(Exception, match="needs the SOLE scoreboard"):
        ProjectConfig(
            project=ProjectMeta(name="t"),
            dut=DutConfig(name="d", reset="", combinational=True),
            agents=[
                _agent([PortConfig(name="x", width=8)], [PortConfig(name="y", width=8)])
            ],
            tests=[TConf(name="t1")],
            analysis=AnalysisConfig(
                scoreboards=[
                    ScoreboardSpec(
                        name="s1",
                        source="a",
                        reference_model=ReferenceModelConfig(language="c"),
                    ),
                    ScoreboardSpec(name="s2", source="a"),
                ]
            ),
        )
