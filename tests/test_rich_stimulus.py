"""S1 deepening — variable-length payload `fields:` + transaction-level `constraints:`.

A `fields:` entry is transaction-only data (a `rand` dynamic array or queue) that is
NOT an interface wire — QuickUVM owns its declaration, field automation, an auto
size-bound and the `constraints:` block; the bus (de)serialization stays user pragma.
Opt-in: an agent with neither is byte-identical (no `trans_c`, no field members).
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    FieldConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    ReferenceModelConfig,
)
from quick_uvm.models import (
    TestConfig as TConf,
)


def _agent(fields=None, constraints=None, inputs=None, outputs=None, name="a"):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        ports={
            "inputs": inputs if inputs is not None else [PortConfig(name="x", width=8)],
            "outputs": outputs
            if outputs is not None
            else [PortConfig(name="y", width=8)],
        },
        fields=fields or [],
        constraints=constraints or [],
    )


def _cfg(**kw):
    rm = kw.pop("reference_model", None)
    agent = _agent(**kw)
    extra = {"reference_model": rm} if rm else {}
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[agent],
        tests=[TConf(name="t1")],
        **extra,
    )


def _trans(tmp_path, **kw):
    Generator(_cfg(**kw)).generate_all(tmp_path)
    return (tmp_path / "a_seq_item.svh").read_text()


# ---- FieldConfig validation ------------------------------------------------


def test_field_bad_element_width_rejected():
    with pytest.raises(Exception, match="element_width"):
        FieldConfig(name="p", element_width=0)


def test_field_bad_size_bounds_rejected():
    with pytest.raises(Exception, match="max_size"):
        FieldConfig(name="p", min_size=10, max_size=4)


def test_field_bad_name_rejected():
    with pytest.raises(Exception):
        FieldConfig(name="2bad")


def test_field_name_collides_with_port_rejected():
    with pytest.raises(Exception, match="collides with a port"):
        _cfg(
            inputs=[PortConfig(name="payload", width=8)],
            fields=[FieldConfig(name="payload")],
        )


def test_duplicate_field_rejected():
    with pytest.raises(Exception, match="duplicate field"):
        _cfg(fields=[FieldConfig(name="p"), FieldConfig(name="p")])


def test_empty_constraint_rejected():
    with pytest.raises(Exception, match="empty transaction constraint"):
        _cfg(constraints=["   "])


# ---- field declaration -----------------------------------------------------


def test_dynamic_array_field_declared_rand(tmp_path):
    txt = _trans(tmp_path, fields=[FieldConfig(name="payload", element_width=8)])
    assert "rand bit [7:0] payload[];" in txt


def test_queue_field_declared(tmp_path):
    txt = _trans(
        tmp_path, fields=[FieldConfig(name="q", element_width=16, kind="queue")]
    )
    assert "rand bit [15:0] q[$];" in txt


def test_nonrand_field_has_no_rand(tmp_path):
    txt = _trans(tmp_path, fields=[FieldConfig(name="p", randomize=False)])
    assert "bit [7:0] p[];" in txt
    assert "rand bit [7:0] p[];" not in txt


def test_field_in_do_copy(tmp_path):
    txt = _trans(tmp_path, fields=[FieldConfig(name="payload")])
    assert "payload = tr.payload;" in txt


def test_field_in_convert2string(tmp_path):
    txt = _trans(tmp_path, fields=[FieldConfig(name="payload")])
    assert '$sformatf("payload=%p  ", payload)' in txt


# ---- field automation (field_macros style) ---------------------------------


def test_dynamic_array_uses_uvm_field_array(tmp_path):
    a = _agent(fields=[FieldConfig(name="payload")])
    a.seq_item_style = "field_macros"
    cfg = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[a],
        tests=[TConf(name="t1")],
    )
    Generator(cfg).generate_all(tmp_path)
    txt = (tmp_path / "a_seq_item.svh").read_text()
    assert "`uvm_field_array_int(payload, UVM_ALL_ON)" in txt


def test_queue_uses_uvm_field_queue(tmp_path):
    a = _agent(fields=[FieldConfig(name="q", kind="queue")])
    a.seq_item_style = "field_macros"
    cfg = ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[a],
        tests=[TConf(name="t1")],
    )
    Generator(cfg).generate_all(tmp_path)
    txt = (tmp_path / "a_seq_item.svh").read_text()
    assert "`uvm_field_queue_int(q, UVM_ALL_ON)" in txt


# ---- constraints -----------------------------------------------------------


def test_auto_size_bound_in_trans_block(tmp_path):
    txt = _trans(
        tmp_path, fields=[FieldConfig(name="payload", min_size=1, max_size=16)]
    )
    assert "constraint trans_c {" in txt
    assert "payload.size() inside {[1:16]};" in txt


def test_transaction_constraints_emitted(tmp_path):
    txt = _trans(
        tmp_path,
        fields=[FieldConfig(name="payload", max_size=16)],
        constraints=["len == payload.size()", "payload.size() dist { [1:4] := 3 }"],
    )
    assert "len == payload.size();" in txt
    assert "payload.size() dist { [1:4] := 3 };" in txt


def test_constraints_only_no_fields(tmp_path):
    # a transaction-level constraint without any field still emits trans_c
    txt = _trans(tmp_path, constraints=["x inside {[1:200]}"])
    assert "constraint trans_c {" in txt
    assert "x inside {[1:200]};" in txt


def test_nonrand_field_alone_emits_no_trans_block(tmp_path):
    # a non-rand field contributes no auto-bound; with no user constraints there
    # is nothing to constrain -> no empty `trans_c {}` block.
    txt = _trans(tmp_path, fields=[FieldConfig(name="p", randomize=False)])
    assert "bit [7:0] p[];" in txt
    assert "trans_c" not in txt


def test_bound_size_false_suppresses_autobound(tmp_path):
    # the field is still declared+randomized, but the user owns sizing: no auto-bound
    txt = _trans(
        tmp_path,
        fields=[FieldConfig(name="payload", bound_size=False)],
        constraints=["payload.size() == 8"],
    )
    assert "rand bit [7:0] payload[];" in txt
    assert "payload.size() inside" not in txt  # auto-bound suppressed
    assert "payload.size() == 8;" in txt


# ---- opt-in / byte-identical ----------------------------------------------


def test_no_fields_no_constraints_is_clean(tmp_path):
    txt = _trans(tmp_path)
    assert "trans_c" not in txt
    assert "[]" not in txt  # no dynamic-array member
    assert "post_randomize" not in txt  # nothing forces a packer


# ---- K0 interaction: fields are not DPI-marshaled (not ports) --------------


def test_field_not_in_dpi_bridge(tmp_path):
    Generator(
        _cfg(
            fields=[FieldConfig(name="payload")],
            reference_model=ReferenceModelConfig(language="c"),
        )
    ).generate_all(tmp_path)
    bridge = (tmp_path / "d_reference_model.svh").read_text()
    assert "payload" not in bridge  # a transaction-only field is never a DPI arg
