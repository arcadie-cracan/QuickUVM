"""S1 — typed/enum transaction fields + per-field constraints (all opt-in).

Black box by default: declaring an `enum` on a port makes QuickUVM generate the
testbench's OWN `<name>_e` typedef and a `rand <name>_e` field that self-constrains
to its legal values — the TB encodes the spec independently of the DUT's types.
The `type` escape hatch references an EXTERNAL SV type (white box, powerful when
needed) and is imported via project.imports. A plain field stays byte-identical.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
)
from quick_uvm.models import (
    TestConfig as TConf,
)

OPS = {"ADD": 0, "SUB": 1, "AND": 2, "OR": 3, "XOR": 4, "SLL": 5, "SRL": 6, "SLT": 7}


def _ag(inputs, outputs=None, *, name="alu", seq_item_style="manual"):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        seq_item_style=seq_item_style,
        ports={
            "inputs": inputs,
            "outputs": outputs or [PortConfig(name="result", width=8)],
        },
    )


def _cfg(agent, *, imports=None):
    return ProjectConfig(
        project=ProjectMeta(name="t", imports=imports or []),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[agent],
        tests=[TConf(name="t1")],
    )


def _trans(tmp_path, agent, **kw):
    Generator(_cfg(agent, **kw)).generate_all(tmp_path)
    return (tmp_path / f"{agent.sequence_item}.svh").read_text()


# ---- enum field (black box) ------------------------------------------------


def test_enum_typedef_generated_before_class(tmp_path):
    agent = _ag([PortConfig(name="op", width=4, enum=OPS)])
    txt = _trans(tmp_path, agent)
    assert "typedef enum logic [3:0] {" in txt
    assert "ADD = 4'd0," in txt
    assert "SLT = 4'd7" in txt
    assert "} op_e;" in txt
    # typedef must precede the class (a package-scope type)
    assert txt.index("} op_e;") < txt.index("class alu_seq_item")


def test_enum_input_field_is_rand_typed(tmp_path):
    agent = _ag([PortConfig(name="op", width=4, enum=OPS)])
    txt = _trans(tmp_path, agent)
    assert "rand op_e op;" in txt
    assert "rand bit [3:0] op;" not in txt  # no plain bit decl


def test_enum_output_field_uses_type(tmp_path):
    agent = _ag(
        [PortConfig(name="a", width=8)],
        outputs=[
            PortConfig(name="status", width=2, enum={"OK": 0, "ERR": 1, "BUSY": 2})
        ],
    )
    txt = _trans(tmp_path, agent)
    assert "} status_e;" in txt
    assert "       status_e status;" in txt


def test_enum_field_macro_uses_uvm_field_enum(tmp_path):
    agent = _ag(
        [PortConfig(name="op", width=4, enum=OPS)], seq_item_style="field_macros"
    )
    txt = _trans(tmp_path, agent)
    assert "`uvm_field_enum(op_e, op, UVM_ALL_ON)" in txt
    assert "`uvm_field_int(op," not in txt  # not the int macro


def test_enum_output_field_macro_nocompare(tmp_path):
    agent = _ag(
        [PortConfig(name="a", width=8)],
        outputs=[PortConfig(name="status", width=2, enum={"OK": 0, "ERR": 1})],
        seq_item_style="field_macros",
    )
    txt = _trans(tmp_path, agent)
    assert "`uvm_field_enum(status_e, status, UVM_ALL_ON | UVM_NOCOMPARE)" in txt


# ---- external type (white box opt-in) --------------------------------------


def test_external_type_field_uses_type_verbatim(tmp_path):
    agent = _ag([PortConfig(name="op", width=4, type="alu_pkg::opcode_e")])
    txt = _trans(tmp_path, agent)
    assert "rand alu_pkg::opcode_e op;" in txt
    assert "typedef enum" not in txt  # no TB enum generated for the type path


def test_external_type_imports_into_tb_pkg(tmp_path):
    agent = _ag([PortConfig(name="op", width=4, type="alu_pkg::opcode_e")])
    Generator(_cfg(agent, imports=["alu_pkg"])).generate_all(tmp_path)
    pkg = (tmp_path / "d_tb_pkg.sv").read_text()
    assert "import alu_pkg::*;" in pkg


# ---- per-field constraint --------------------------------------------------


def test_field_constraint_emitted_in_block(tmp_path):
    agent = _ag(
        [
            PortConfig(name="a", width=8, constraint="a != 0"),
            PortConfig(name="b", width=8),
        ]
    )
    txt = _trans(tmp_path, agent)
    assert "constraint qcfg_c {" in txt
    assert "a != 0;" in txt


def test_no_constraint_block_when_none(tmp_path):
    agent = _ag([PortConfig(name="a", width=8)])
    txt = _trans(tmp_path, agent)
    assert "qcfg_c" not in txt


# ---- plain field stays byte-identical --------------------------------------


def test_plain_field_unchanged(tmp_path):
    """A plain {name,width,randomize} field emits exactly the legacy decls."""
    agent = _ag(
        [
            PortConfig(name="a", width=8),
            PortConfig(name="en", width=1, randomize=False),
        ],
        outputs=[PortConfig(name="result", width=8)],
    )
    txt = _trans(tmp_path, agent)
    assert "  rand bit [7:0] a;" in txt
    assert "       bit en;" in txt
    assert "       logic [7:0] result;" in txt
    assert "typedef enum" not in txt
    assert "qcfg_c" not in txt


# ---- validation + sv_type --------------------------------------------------


def test_enum_and_type_mutually_exclusive():
    with pytest.raises(Exception, match="at most one type specifier"):
        PortConfig(name="op", width=4, enum=OPS, type="alu_pkg::opcode_e")


def test_sv_type_property():
    assert PortConfig(name="op", width=4, enum=OPS).sv_type == "op_e"
    assert (
        PortConfig(name="op", type="alu_pkg::opcode_e").sv_type == "alu_pkg::opcode_e"
    )
    assert PortConfig(name="a", width=8).sv_type == "bit [7:0]"
    assert PortConfig(name="f", width=1).sv_type == "bit"


# ---- enum value validation (fail closed on illegal SV) ---------------------


def test_enum_value_out_of_range_rejected():
    with pytest.raises(Exception, match="does not fit"):
        PortConfig(name="op", width=2, enum={"A": 0, "B": 4})


def test_enum_negative_value_rejected():
    with pytest.raises(Exception, match="does not fit"):
        PortConfig(name="op", width=4, enum={"A": -1, "B": 1})


def test_enum_duplicate_values_rejected():
    with pytest.raises(Exception, match="must be unique"):
        PortConfig(name="op", width=4, enum={"A": 0, "B": 0})


def test_empty_enum_rejected():
    with pytest.raises(Exception, match="at least one value"):
        PortConfig(name="op", width=4, enum={})


def test_enum_value_at_width_boundary_ok():
    # 7 is the max in 3 bits — must be accepted, 8 must not
    PortConfig(name="op", width=3, enum={"LO": 0, "HI": 7})
    with pytest.raises(Exception, match="does not fit"):
        PortConfig(name="op", width=3, enum={"LO": 0, "HI": 8})


# ---- constraint placement validation ---------------------------------------


def _agent_with(inputs, outputs):
    return AgentConfig(
        name="alu",
        interface="alu_if",
        sequence_item="alu_seq_item",
        ports={"inputs": inputs, "outputs": outputs},
    )


def test_constraint_on_output_rejected():
    with pytest.raises(Exception, match="outputs are sampled"):
        _agent_with(
            [PortConfig(name="a", width=8)],
            [PortConfig(name="result", width=8, constraint="result < 100")],
        )


def test_constraint_on_nonrand_input_rejected():
    with pytest.raises(Exception, match="randomize=false"):
        _agent_with(
            [PortConfig(name="en", width=1, randomize=False, constraint="en == 1")],
            [PortConfig(name="result", width=8)],
        )


def test_same_name_in_inputs_and_outputs_rejected():
    # one field -> one transaction member (and one DPI-C formal, K0); a name in
    # both lists would double-declare. Reject it at config time.
    with pytest.raises(Exception, match="both"):
        _agent_with(
            [PortConfig(name="data", width=8)],
            [PortConfig(name="data", width=8, randomize=False)],
        )


# ---- monitor casts logic->enum (IEEE 1800.2 strong typing) -----------------


def test_monitor_casts_enum_field_combinational(tmp_path):
    agent = _ag(
        [PortConfig(name="a", width=8), PortConfig(name="op", width=4, enum=OPS)]
    )
    Generator(_cfg(agent)).generate_all(tmp_path)
    mon = (tmp_path / "alu_monitor.svh").read_text()
    assert "void'($cast(t.op, vif.mon_cb.op));" in mon
    assert "t.op = vif.mon_cb.op;" not in mon  # no bare logic->enum assignment
    # plain fields keep the bare assignment (byte-identical)
    assert "t.a = vif.mon_cb.a;" in mon


def test_monitor_plain_field_uncast(tmp_path):
    agent = _ag([PortConfig(name="a", width=8)])
    Generator(_cfg(agent)).generate_all(tmp_path)
    mon = (tmp_path / "alu_monitor.svh").read_text()
    assert "t.a = vif.mon_cb.a;" in mon
    assert "$cast" not in mon


# ---- enum-aware coverage + symbolic printing -------------------------------


def test_enum_coverpoint_uses_auto_bins(tmp_path):
    agent = _ag([PortConfig(name="op", width=4, enum=OPS)])
    Generator(_cfg(agent)).generate_all(tmp_path)
    cov = (tmp_path / "alu_cov.svh").read_text()
    assert "op_cp : coverpoint tr.op;" in cov  # auto one-bin-per-label
    assert "op_bins[8]" not in cov  # not the generic range partition


def test_enum_printed_by_name(tmp_path):
    agent = _ag([PortConfig(name="op", width=4, enum=OPS)])
    txt = _trans(tmp_path, agent)
    assert 'op=%s  ", op.name())' in txt
