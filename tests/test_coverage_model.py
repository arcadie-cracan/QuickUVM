"""V1 — functional coverage from fields (opt-in coverage_models).

An opt-in `coverage_models:` block generates a real covergroup (config-driven
coverpoints + bins + crosses) in <agent>_cover, replacing the generic auto-bin
stub. Sampled on the monitor's analysis write (no new plumbing). Byte-identical
when absent. Black box: bins encode the spec's interesting values, not DUT
internals.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    CoverageBin,
    CoverageModel,
    Coverpoint,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
)
from quick_uvm.models import (
    TestConfig as TConf,
)

OPS = {"ADD": 0, "SUB": 1, "AND": 2, "OR": 3, "XOR": 4, "SLL": 5, "SRL": 6, "SLT": 7}


def _agent():
    return AgentConfig(
        name="alu",
        interface="alu_if",
        transaction="alu_seq_item",
        ports={
            "inputs": [
                PortConfig(name="a", width=8),
                PortConfig(name="b", width=8),
                PortConfig(name="op", width=4, enum=OPS),
            ],
            "outputs": [
                PortConfig(name="result", width=8),
                PortConfig(name="carry", width=1),
            ],
        },
    )


def _cfg(coverage_models=None, agent=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[agent or _agent()],
        tests=[TConf(name="t1")],
        coverage_models=coverage_models or [],
    )


def _cover(tmp_path, coverage_models, agent=None):
    Generator(_cfg(coverage_models, agent)).generate_all(tmp_path)
    return (tmp_path / "alu_cover.svh").read_text()


_ALU_MODEL = CoverageModel(
    agent="alu",
    coverpoints=[
        Coverpoint(field="op"),
        Coverpoint(
            field="a",
            bins=[
                CoverageBin(name="zero", value=0),
                CoverageBin(name="max", value=255),
                CoverageBin(name="mid", range=(1, 254)),
            ],
        ),
        Coverpoint(field="carry"),
    ],
    crosses=[["op", "a"]],
)


# ---- generated covergroup --------------------------------------------------


def test_enum_coverpoint_auto_bins(tmp_path):
    cov = _cover(tmp_path, [_ALU_MODEL])
    assert "op_cp : coverpoint tr.op;" in cov  # enum -> auto one-bin-per-label


def test_explicit_bins_emitted(tmp_path):
    cov = _cover(tmp_path, [_ALU_MODEL])
    assert "a_cp : coverpoint tr.a {" in cov
    assert "bins zero = {0};" in cov
    assert "bins max = {255};" in cov
    assert "bins mid = {[1:254]};" in cov


def test_values_bin_emitted(tmp_path):
    model = CoverageModel(
        agent="alu",
        coverpoints=[
            Coverpoint(
                field="a",
                bins=[CoverageBin(name="lowbits", values=[1, 2, 4, 8])],
            )
        ],
    )
    cov = _cover(tmp_path, [model])
    assert "bins lowbits = {1, 2, 4, 8};" in cov


def test_one_bit_field_needs_no_bins(tmp_path):
    cov = _cover(tmp_path, [_ALU_MODEL])
    assert "carry_cp : coverpoint tr.carry;" in cov  # 1-bit auto


def test_cross_emitted_and_named(tmp_path):
    cov = _cover(tmp_path, [_ALU_MODEL])
    assert "op_x_a : cross op_cp, a_cp;" in cov


def test_per_coverpoint_at_least(tmp_path):
    model = CoverageModel(
        agent="alu",
        coverpoints=[Coverpoint(field="op", at_least=50)],
    )
    cov = _cover(tmp_path, [model])
    assert "op_cp : coverpoint tr.op {" in cov
    assert "option.at_least = 50;" in cov


def test_three_way_cross(tmp_path):
    model = CoverageModel(
        agent="alu",
        coverpoints=[
            Coverpoint(field="op"),
            Coverpoint(field="carry"),
            Coverpoint(field="a", bins=[CoverageBin(name="z", value=0)]),
        ],
        crosses=[["op", "a", "carry"]],
    )
    cov = _cover(tmp_path, [model])
    assert "op_x_a_x_carry : cross op_cp, a_cp, carry_cp;" in cov


# ---- byte-identical when absent --------------------------------------------


def test_no_model_keeps_generic_stub(tmp_path):
    cov = _cover(tmp_path, [])
    # the legacy generic partition, unchanged
    assert "a_cp : coverpoint tr.a {bins a_bins[8] = {[0:$]};}" in cov
    assert "op_cp : coverpoint tr.op;" in cov  # enum stayed auto (S1)
    assert "cross" not in cov


# ---- validation ------------------------------------------------------------


def test_unknown_agent_rejected():
    with pytest.raises(Exception, match="unknown agent"):
        _cfg([CoverageModel(agent="nope", coverpoints=[Coverpoint(field="a")])])


def test_unknown_field_rejected():
    with pytest.raises(Exception, match="not a port"):
        _cfg([CoverageModel(agent="alu", coverpoints=[Coverpoint(field="ghost")])])


def test_wide_plain_field_without_bins_rejected():
    # `a` is 8-bit plain — an auto-partition would be meaningless, so require bins
    with pytest.raises(Exception, match="needs explicit bins"):
        _cfg([CoverageModel(agent="alu", coverpoints=[Coverpoint(field="a")])])


def test_bin_value_out_of_range_rejected():
    with pytest.raises(Exception, match="outside 0..15"):
        _cfg(
            [
                CoverageModel(
                    agent="alu",
                    coverpoints=[
                        Coverpoint(field="op", bins=[CoverageBin(name="bad", value=99)])
                    ],
                )
            ]
        )


def test_cross_unknown_coverpoint_rejected():
    with pytest.raises(Exception, match="not a declared coverpoint"):
        CoverageModel(
            agent="alu",
            coverpoints=[Coverpoint(field="op")],
            crosses=[["op", "a"]],  # a is not a coverpoint here
        )


def test_duplicate_model_for_agent_rejected():
    with pytest.raises(Exception, match="duplicate model"):
        _cfg(
            [
                CoverageModel(agent="alu", coverpoints=[Coverpoint(field="op")]),
                CoverageModel(agent="alu", coverpoints=[Coverpoint(field="carry")]),
            ]
        )


def test_empty_coverpoints_rejected():
    with pytest.raises(Exception, match="at least one"):
        CoverageModel(agent="alu", coverpoints=[])


def test_bin_needs_exactly_one_spec():
    with pytest.raises(Exception, match="exactly one"):
        CoverageBin(name="x", value=1, range=(0, 3))
    with pytest.raises(Exception, match="exactly one"):
        CoverageBin(name="x")


def test_bin_bad_range_rejected():
    with pytest.raises(Exception, match="low .* > high"):
        CoverageBin(name="x", range=(10, 2))


# ---- identifier / uniqueness / wiring validation (fail closed) -------------


def test_reserved_word_bin_name_rejected():
    with pytest.raises(Exception, match="reserved word"):
        CoverageBin(name="logic", value=2)


def test_illegal_bin_name_rejected():
    with pytest.raises(Exception, match="legal SystemVerilog identifier"):
        CoverageBin(name="hi there", value=2)
    with pytest.raises(Exception, match="legal SystemVerilog identifier"):
        CoverageBin(name="2cool", value=2)


def test_duplicate_bin_name_in_coverpoint_rejected():
    with pytest.raises(Exception, match="duplicate bin name"):
        Coverpoint(
            field="a",
            bins=[CoverageBin(name="dup", value=0), CoverageBin(name="dup", value=1)],
        )


def test_duplicate_coverpoint_field_rejected():
    with pytest.raises(Exception, match="duplicate coverpoint"):
        CoverageModel(
            agent="alu",
            coverpoints=[Coverpoint(field="op"), Coverpoint(field="op")],
        )


def test_at_least_below_one_rejected():
    with pytest.raises(Exception, match="at_least must be >= 1"):
        Coverpoint(field="op", at_least=0)
    with pytest.raises(Exception, match="at_least must be >= 1"):
        Coverpoint(field="op", at_least=-5)


def test_coverage_model_on_uncovered_agent_rejected():
    # two agents, no analysis block -> only the primary (a0) is covered; a model
    # on the secondary agent would compile but never be sampled.
    a0 = AgentConfig(
        name="a0",
        interface="a0_if",
        transaction="a0_seq_item",
        ports={"inputs": [PortConfig(name="x", width=1)], "outputs": []},
    )
    a1 = AgentConfig(
        name="a1",
        interface="a1_if",
        transaction="a1_seq_item",
        ports={"inputs": [PortConfig(name="y", width=1)], "outputs": []},
    )
    with pytest.raises(Exception, match="not wired for coverage"):
        ProjectConfig(
            project=ProjectMeta(name="t"),
            dut=DutConfig(name="d", reset="", combinational=True),
            agents=[a0, a1],
            tests=[TConf(name="t1")],
            coverage_models=[
                CoverageModel(agent="a1", coverpoints=[Coverpoint(field="y")])
            ],
        )


# ---- sv_bin rendering ------------------------------------------------------


def test_sv_bin_property():
    assert CoverageBin(name="x", value=7).sv_bin == "{7}"
    assert CoverageBin(name="x", range=(1, 254)).sv_bin == "{[1:254]}"
    assert CoverageBin(name="x", values=[1, 2, 4]).sv_bin == "{1, 2, 4}"
