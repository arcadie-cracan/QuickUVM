"""S2 — per-agent sequence library + test sequence selection (opt-in).

An agent's `sequences:` list generates a library of sequence classes (random /
incrementing concrete; directed/reset/error skeleton); a test's `sequence:`
selector starts a chosen library sequence on that agent's sequencer instead of
the default <primary>_sequence. Byte-identical when neither is used.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    SequenceConfig,
)
from quick_uvm.models import (
    TestConfig as TConf,
)
from quick_uvm.models import (
    TestSeqSel as SeqSel,
)

OPS = {"ADD": 0, "SUB": 1}


def _agent(sequences=None):
    return AgentConfig(
        name="alu",
        interface="alu_if",
        sequence_item="alu_seq_item",
        ports={
            "inputs": [
                PortConfig(name="a", width=8),
                PortConfig(name="op", width=4, enum=OPS),
            ],
            "outputs": [PortConfig(name="result", width=8)],
        },
        sequences=sequences or [],
    )


def _cfg(sequences=None, tests=None, agent=None):
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[agent or _agent(sequences)],
        tests=tests or [TConf(name="t1")],
    )


def _gen(tmp_path, sequences=None, tests=None, agent=None):
    Generator(_cfg(sequences, tests, agent)).generate_all(tmp_path)
    return tmp_path


# ---- generated library sequences -------------------------------------------


def test_random_sequence_body(tmp_path):
    _gen(tmp_path, sequences=[SequenceConfig(name="alu_rand", kind="random", count=64)])
    seq = (tmp_path / "alu_rand.svh").read_text()
    assert "class alu_rand extends uvm_sequence #(alu_seq_item);" in seq
    assert "int unsigned count = 64;" in seq  # settable member (S2 override)
    assert "repeat(count) do_item(tr);" in seq
    assert "tr.randomize()" in seq


def test_incrementing_sequence_body(tmp_path):
    _gen(
        tmp_path,
        sequences=[
            SequenceConfig(name="alu_incr", kind="incrementing", count=16, field="a")
        ],
    )
    seq = (tmp_path / "alu_incr.svh").read_text()
    assert "int unsigned count = 16;" in seq
    assert "for (int unsigned i = 0; i < count; i++) do_item(tr, i);" in seq
    assert "tr.a == 8'(i);" in seq  # field stepped, width-cast


# ---- S2 deepening: sequence-of-sequences (nested) --------------------------


def test_nested_sequence_body(tmp_path):
    _gen(
        tmp_path,
        sequences=[
            SequenceConfig(name="alu_rand", kind="random"),
            SequenceConfig(name="alu_incr", kind="incrementing", field="a"),
            SequenceConfig(
                name="alu_combo", kind="nested", steps=["alu_incr", "alu_rand"]
            ),
        ],
    )
    seq = (tmp_path / "alu_combo.svh").read_text()
    assert "alu_incr step_0;" in seq
    assert "alu_rand step_1;" in seq
    assert 'step_0 = alu_incr::type_id::create("step_0");' in seq
    assert "step_0.start(m_sequencer);" in seq
    assert "step_1.start(m_sequencer);" in seq
    assert "int count" not in seq  # a nested seq has no item count


def test_nested_repeated_step_gets_unique_handles(tmp_path):
    _gen(
        tmp_path,
        sequences=[
            SequenceConfig(name="alu_rand", kind="random"),
            SequenceConfig(
                name="alu_combo", kind="nested", steps=["alu_rand", "alu_rand"]
            ),
        ],
    )
    seq = (tmp_path / "alu_combo.svh").read_text()
    assert "alu_rand step_0;" in seq
    assert "alu_rand step_1;" in seq  # repeated step -> distinct handle


# ---- S2 deepening: per-test count override ---------------------------------


def test_count_override_emitted(tmp_path):
    _gen(
        tmp_path,
        sequences=[SequenceConfig(name="alu_rand", kind="random", count=64)],
        tests=[
            TConf(name="t1", sequence=SeqSel(agent="alu", name="alu_rand", count=8))
        ],
    )
    test = (tmp_path / "t1.svh").read_text()
    assert "seq.count = 8;" in test


def test_no_count_override_no_assignment(tmp_path):
    _gen(
        tmp_path,
        sequences=[SequenceConfig(name="alu_rand", kind="random")],
        tests=[TConf(name="t1", sequence=SeqSel(agent="alu", name="alu_rand"))],
    )
    test = (tmp_path / "t1.svh").read_text()
    assert "seq.count" not in test


# ---- S2 deepening validation -----------------------------------------------


def test_nested_requires_steps():
    with pytest.raises(Exception, match="requires a non-empty 'steps'"):
        SequenceConfig(name="s", kind="nested")


def test_steps_on_non_nested_rejected():
    with pytest.raises(Exception, match="'steps' only applies to kind 'nested'"):
        SequenceConfig(name="s", kind="random", steps=["x"])


def test_nested_self_reference_rejected():
    with pytest.raises(Exception, match="lists itself as a step"):
        _cfg(sequences=[SequenceConfig(name="s", kind="nested", steps=["s"])])


def test_nested_unknown_step_rejected():
    with pytest.raises(Exception, match="not a declared sequence"):
        _cfg(
            sequences=[
                SequenceConfig(name="alu_rand", kind="random"),
                SequenceConfig(name="combo", kind="nested", steps=["ghost"]),
            ]
        )


def test_nested_of_nested_rejected():
    with pytest.raises(Exception, match="is itself nested"):
        _cfg(
            sequences=[
                SequenceConfig(name="alu_rand", kind="random"),
                SequenceConfig(name="inner", kind="nested", steps=["alu_rand"]),
                SequenceConfig(name="outer", kind="nested", steps=["inner"]),
            ]
        )


def test_count_override_on_nested_rejected():
    with pytest.raises(Exception, match="nested sequence-of-sequences and has no"):
        _cfg(
            sequences=[
                SequenceConfig(name="alu_rand", kind="random"),
                SequenceConfig(name="combo", kind="nested", steps=["alu_rand"]),
            ],
            tests=[
                TConf(name="t1", sequence=SeqSel(agent="alu", name="combo", count=5))
            ],
        )


def test_count_override_below_one_rejected():
    with pytest.raises(Exception, match="count must be >= 1"):
        SeqSel(agent="alu", name="alu_rand", count=0)


def test_skeleton_sequence_has_pragma_body(tmp_path):
    for kind in ("directed", "reset", "error"):
        _gen(tmp_path, sequences=[SequenceConfig(name=f"alu_{kind}", kind=kind)])
        seq = (tmp_path / f"alu_{kind}.svh").read_text()
        assert "// pragma quickuvm custom body begin" in seq
        assert "// pragma quickuvm custom body end" in seq


def test_library_sequences_included_in_tb_pkg(tmp_path):
    _gen(
        tmp_path,
        sequences=[
            SequenceConfig(name="alu_rand", kind="random"),
            SequenceConfig(name="alu_incr", kind="incrementing", field="a"),
        ],
    )
    pkg = (tmp_path / "d_tb_pkg.sv").read_text()
    assert '`include "alu_seq.svh"' in pkg  # the default is still there
    assert '`include "alu_rand.svh"' in pkg
    assert '`include "alu_incr.svh"' in pkg


# ---- test selection --------------------------------------------------------


def test_selector_starts_chosen_sequence(tmp_path):
    _gen(
        tmp_path,
        sequences=[SequenceConfig(name="alu_incr", kind="incrementing", field="a")],
        tests=[TConf(name="t_incr", sequence=SeqSel(agent="alu", name="alu_incr"))],
    )
    test = (tmp_path / "t_incr.svh").read_text()
    assert "alu_incr seq;" in test
    assert 'seq = alu_incr::type_id::create("seq");' in test
    assert "seq.start(e.alu_agnt.sqr);" in test


def test_no_selector_is_byte_identical_default(tmp_path):
    # the default run_phase starts <primary>_sequence on the primary sequencer
    _gen(tmp_path, tests=[TConf(name="t1")])
    test = (tmp_path / "t1.svh").read_text()
    assert "alu_seq seq;" in test
    assert "seq.start(e.alu_agnt.sqr);" in test


# ---- validation ------------------------------------------------------------


def test_incrementing_without_field_rejected():
    with pytest.raises(Exception, match="requires a 'field'"):
        SequenceConfig(name="s", kind="incrementing")


def test_field_on_non_incrementing_rejected():
    with pytest.raises(Exception, match="only applies to kind 'incrementing'"):
        SequenceConfig(name="s", kind="random", field="a")


def test_incrementing_on_enum_field_rejected():
    with pytest.raises(Exception, match="plain integral field"):
        _cfg(sequences=[SequenceConfig(name="s", kind="incrementing", field="op")])


def test_incrementing_on_unknown_field_rejected():
    with pytest.raises(Exception, match="not a randomizable input"):
        _cfg(sequences=[SequenceConfig(name="s", kind="incrementing", field="ghost")])


def test_duplicate_sequence_name_rejected():
    with pytest.raises(Exception, match="duplicate sequence name"):
        _cfg(
            sequences=[
                SequenceConfig(name="s", kind="random"),
                SequenceConfig(name="s", kind="random"),
            ]
        )


def test_sequence_name_collides_with_default_rejected():
    with pytest.raises(Exception, match="collides with the generated default"):
        _cfg(sequences=[SequenceConfig(name="alu_seq", kind="random")])


def test_selector_unknown_agent_rejected():
    with pytest.raises(Exception, match="unknown agent"):
        _cfg(
            sequences=[SequenceConfig(name="alu_rand", kind="random")],
            tests=[TConf(name="t", sequence=SeqSel(agent="nope", name="alu_rand"))],
        )


def test_selector_unknown_sequence_rejected():
    with pytest.raises(Exception, match="not a declared sequence"):
        _cfg(
            sequences=[SequenceConfig(name="alu_rand", kind="random")],
            tests=[TConf(name="t", sequence=SeqSel(agent="alu", name="ghost"))],
        )


def test_count_below_one_rejected():
    with pytest.raises(Exception, match="count must be >= 1"):
        SequenceConfig(name="s", kind="random", count=0)


def test_illegal_sequence_name_rejected():
    with pytest.raises(Exception, match="legal SystemVerilog identifier"):
        SequenceConfig(name="2bad", kind="random")


def test_reserved_word_sequence_name_rejected():
    with pytest.raises(Exception, match="reserved word"):
        SequenceConfig(name="logic", kind="random")


def test_incrementing_on_constrained_field_rejected():
    with pytest.raises(Exception, match="stepping and constraining"):
        AgentConfig(
            name="alu",
            interface="alu_if",
            sequence_item="alu_seq_item",
            ports={
                "inputs": [PortConfig(name="a", width=8, constraint="a < 100")],
                "outputs": [PortConfig(name="result", width=8)],
            },
            sequences=[SequenceConfig(name="s", kind="incrementing", field="a")],
        )


def test_selector_on_passive_agent_rejected():
    agent = AgentConfig(
        name="mon",
        interface="mon_if",
        sequence_item="mon_seq_item",
        active=False,
        ports={
            "inputs": [PortConfig(name="a", width=8)],
            "outputs": [PortConfig(name="result", width=8)],
        },
        sequences=[SequenceConfig(name="mon_rand", kind="random")],
    )
    with pytest.raises(Exception, match="passive agent"):
        _cfg(
            agent=agent,
            tests=[TConf(name="t", sequence=SeqSel(agent="mon", name="mon_rand"))],
        )
