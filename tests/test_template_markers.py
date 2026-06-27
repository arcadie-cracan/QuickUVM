"""Regression guard: pragma markers must always render isolated on their own lines.

A latent defect had Jinja ``{%-`` trimming glue generated code onto marker lines,
which silently broke user-code preservation.  This test exercises several config
shapes (multiple agents, field_macros, no-reset, mixed widths) and asserts that
every generated file has well-formed, un-glued markers.
"""

from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.merger import _MARKER_RE, validate_markers
from quick_uvm.models import (
    AgentConfig,
    AnalysisConfig,
    ClockConfig,
    CoverageBin,
    CoverageModel,
    Coverpoint,
    CrossBin,
    CrossSpec,
    DutConfig,
    FieldConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    ReferenceModelConfig,
    RegisterModelConfig,
    ScoreboardSpec,
    SequenceConfig,
    StructMember,
    TransitionBin,
)
from quick_uvm.models import (
    TestConfig as TConf,  # aliased so pytest doesn't try to collect it
)

EXAMPLE_CONFIG = (
    Path(__file__).parent.parent / "examples" / "simple_reg" / "simple_reg.yaml"
)


def _agent(name, **kw):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_trans",
        ports={
            "outputs": [PortConfig(name="dout", width=16, randomize=False)],
            "inputs": [
                PortConfig(name="din", width=8),
                PortConfig(name="rst_n", width=1),
            ],
        },
        **kw,
    )


def _cfg(**over):
    base = dict(
        project=ProjectMeta(name="t", author="a", year=2026),
        dut=DutConfig(name="t_dut"),
        clock=ClockConfig(),
        agents=[_agent("a0")],
        tests=[TConf(name="test1")],
    )
    base.update(over)
    return ProjectConfig(**base)


CONFIGS = {
    "example": ProjectConfig.from_yaml(EXAMPLE_CONFIG),
    "two_agents_two_tests": _cfg(
        agents=[_agent("a0"), _agent("a1", seq_item_style="field_macros")],
        tests=[TConf(name="test1"), TConf(name="test2", num_items=5)],
    ),
    "no_reset": _cfg(dut=DutConfig(name="nr", reset="")),
    "field_macros": _cfg(agents=[_agent("fm", seq_item_style="field_macros")]),
    "with_analysis": _cfg(
        agents=[_agent("a0"), _agent("a1")],
        analysis=AnalysisConfig(
            coverage=["a0", "a1"],
            scoreboards=[ScoreboardSpec(name="sbd", source="a0")],
        ),
    ),
    "with_regmodel": _cfg(
        agents=[_agent("a0")],
        register_model=RegisterModelConfig(
            package="my_reg_uvm_pkg",
            block="my_reg_block_c",
            bus_agent="a0",
            adapter="a0_reg_adapter",
            frontdoor="a0_reg_frontdoor",
            # C5 — also exercises the csr_test template's csr_test_pre/post markers.
            csr_tests=["hw_reset", "bit_bash", "rw"],
        ),
    ),
    # K0 — the DPI-C path is the only feature with a user-editable pragma in a
    # generated .c file; cover it here too (history of {%- marker-gluing defects).
    "dpi_c": _cfg(reference_model=ReferenceModelConfig(language="c")),
    "dpi_c_two_agents": _cfg(
        agents=[_agent("a0"), _agent("a1")],
        reference_model=ReferenceModelConfig(language="c"),
    ),
    # S1 — a transaction with a var-length payload field + transaction constraints
    # (exercises the new `trans_c` block + post-input field declarations).
    "rich_stimulus": _cfg(
        agents=[
            _agent(
                "a0",
                fields=[FieldConfig(name="payload", element_width=8, max_size=16)],
                constraints=["din < payload.size()"],
            )
        ],
    ),
    # S2 — a sequence library with a nested sequence-of-sequences + a count
    # override (exercises the nested branch + count member in the seq template).
    "nested_seq": _cfg(
        agents=[
            _agent(
                "a0",
                sequences=[
                    SequenceConfig(name="warm", kind="random", count=4),
                    SequenceConfig(name="combo", kind="nested", steps=["warm", "warm"]),
                ],
            )
        ],
        tests=[
            TConf(name="test1", sequence={"agent": "a0", "name": "warm", "count": 3})
        ],
    ),
    # V1 closure — illegal_bins / ignore_bins / transition bins + option.goal
    # (exercises the new coverpoint-body branches in the coverage template).
    "coverage_closure": _cfg(
        coverage_models=[
            CoverageModel(
                agent="a0",
                goal=90,
                coverpoints=[
                    Coverpoint(
                        field="din",
                        bins=[CoverageBin(name="lo", range=(0, 127))],
                        illegal_bins=[CoverageBin(name="bad", value=255)],
                        ignore_bins=[CoverageBin(name="dontcare", value=128)],
                        transitions=[TransitionBin(name="z2one", seq="0 => 1")],
                    )
                ],
            )
        ],
    ),
    # V1 — a binsof-refined cross (exercises the cross-body branch in coverage).
    "binsof_cross": _cfg(
        coverage_models=[
            CoverageModel(
                agent="a0",
                coverpoints=[
                    Coverpoint(
                        field="din", bins=[CoverageBin(name="lo", range=(0, 127))]
                    ),
                    Coverpoint(field="rst_n"),
                    Coverpoint(field="dout", auto_bin_max=8),  # wide field auto-binned
                ],
                crosses=[
                    CrossSpec(
                        name="dr",
                        fields=["din", "rst_n"],
                        bins=[CrossBin(name="sel", select="binsof(din_cp.lo)")],
                    )
                ],
            )
        ],
    ),
    # S1 — packed composite fields: a packed struct + a packed array port
    # (exercises the struct typedef + typed declarations in the transaction).
    "packed_fields": _cfg(
        agents=[
            AgentConfig(
                name="a0",
                interface="a0_if",
                sequence_item="a0_trans",
                ports={
                    "inputs": [
                        PortConfig(
                            name="hdr",
                            struct=[
                                # nested struct + enum members -> named typedefs
                                StructMember(
                                    name="tag",
                                    struct=[
                                        StructMember(
                                            name="cls", width=4, enum={"A": 0, "B": 1}
                                        ),
                                        StructMember(name="id", width=4),
                                    ],
                                ),
                                StructMember(name="en", width=1),
                            ],
                        ),
                        PortConfig(name="lanes", packed_dims=[4, 8]),
                    ],
                    "outputs": [PortConfig(name="dout", width=16, randomize=False)],
                },
            )
        ],
    ),
    # S1 — a rand input with rand_mode disabled by default (exercises the
    # rand_mode(0) call emitted into the transaction's new()).
    "rand_mode": _cfg(
        agents=[
            AgentConfig(
                name="a0",
                interface="a0_if",
                sequence_item="a0_trans",
                ports={
                    "inputs": [
                        PortConfig(name="din", width=8),
                        PortConfig(name="ctrl", width=4, rand_mode=False),
                    ],
                    "outputs": [PortConfig(name="dout", width=16, randomize=False)],
                },
            )
        ],
    ),
    # A2 — a two-stream scoreboard (source → predictor → monitor) with emit_when on
    # both agents (exercises the two-stream reference_model predict body + the
    # monitor emit-gate branch markers).
    "two_stream": _cfg(
        agents=[
            AgentConfig(
                name="req",
                interface="req_if",
                sequence_item="req_seq_item",
                emit_when="req_valid",
                ports={
                    "inputs": [
                        PortConfig(name="req_valid", width=1),
                        PortConfig(name="req_data", width=8),
                    ]
                },
            ),
            AgentConfig(
                name="rsp",
                interface="rsp_if",
                sequence_item="rsp_seq_item",
                active=False,
                emit_when="rsp_valid",
                ports={
                    "outputs": [
                        PortConfig(name="rsp_valid", width=1, randomize=False),
                        PortConfig(name="rsp_data", width=8, randomize=False),
                    ]
                },
            ),
        ],
        analysis=AnalysisConfig(
            scoreboards=[ScoreboardSpec(name="sbd", source="req", monitor="rsp")]
        ),
    ),
}


def _bad_markers(text: str):
    """Return (validation_errors, glued_marker_lines) for *text*."""
    errors = validate_markers(text)
    glued = [
        ln
        for ln in text.splitlines()
        if "pragma quickuvm custom" in ln and not _MARKER_RE.match(ln)
    ]
    return errors, glued


@pytest.mark.parametrize("cfg_name", list(CONFIGS))
def test_no_glued_or_malformed_markers(cfg_name, tmp_path):
    gen = Generator(CONFIGS[cfg_name])
    gen.generate_all(tmp_path / cfg_name)
    problems = []
    for f in sorted((tmp_path / cfg_name).iterdir()):
        errors, glued = _bad_markers(f.read_text())
        if errors or glued:
            problems.append((f.name, errors, glued))
    assert not problems, f"marker problems in {cfg_name}: {problems}"


def test_monitor_sampling_code_is_active_not_commented(tmp_path):
    """Regression: `{%-` trimming once glued sampling assignments onto `//` comment
    lines, silently commenting out the monitor's DUT sampling. Guard against it."""
    Generator(CONFIGS["example"]).generate_all(tmp_path)
    text = (tmp_path / "reg_monitor.svh").read_text()
    lines = [ln.strip() for ln in text.splitlines()]
    for stmt in ("t.din = vif.din;", "t.dout = vif.cb1.dout;"):
        assert stmt in lines, f"{stmt!r} not an active line — possibly commented out"
    # No line may carry code after a // comment (comment-swallows-code).
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("//"):
            continue  # pure comment / pragma line is fine
        if "//" in s and "pragma" not in s:
            after = s.split("//", 1)[1]
            assert "=" not in after and ";" not in after, f"code after // on: {ln!r}"


@pytest.mark.parametrize("cfg_name", list(CONFIGS))
def test_regeneration_is_idempotent(cfg_name, tmp_path):
    """A pristine tree regenerated yields no orphans and no changes."""
    gen = Generator(CONFIGS[cfg_name])
    out = tmp_path / cfg_name
    gen.generate_all(out)
    results = gen.generate_all(out)  # second pass — must be clean
    assert all(status == "unchanged" for status, _ in results), results
