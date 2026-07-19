"""S1 — packed composite port fields: packed arrays + packed structs.

A port may declare a fixed-width composite type: a multi-dim packed array
(`packed_dims`) or a packed struct (`struct`). These ride the interface as raw
bits (width = `bit_width`) but are declared as their composite SV type in the
transaction (a `<name>_t` typedef for a struct, inline `bit [..][..]` for an
array). Mutually exclusive with enum/type; byte-identical when unused.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import (
    AgentConfig,
    DutConfig,
    PortConfig,
    ProjectConfig,
    ProjectMeta,
    ReferenceModelConfig,
    SequenceConfig,
    StructMember,
)
from quick_uvm.models import (
    TestConfig as TConf,
)

HDR = [StructMember(name="tag", width=8), StructMember(name="en", width=1)]


def _agent(inputs, outputs=None, name="a", **kw):
    return AgentConfig(
        name=name,
        interface=f"{name}_if",
        sequence_item=f"{name}_seq_item",
        ports={"inputs": inputs, "outputs": outputs or [PortConfig(name="o", width=8)]},
        **kw,
    )


def _cfg(inputs, **kw):
    rm = kw.pop("reference_model", None)
    if rm is not None:
        from quick_uvm.models import AnalysisConfig, ScoreboardSpec

        kw["analysis"] = AnalysisConfig(
            scoreboards=[ScoreboardSpec(name="sbd", source="a", reference_model=rm)]
        )
    return ProjectConfig(
        project=ProjectMeta(name="t"),
        dut=DutConfig(name="d", reset="", combinational=True),
        agents=[_agent(inputs)],
        tests=[TConf(name="t1")],
        **kw,
    )


def _gen(tmp_path, inputs):
    Generator(_cfg(inputs)).generate_all(tmp_path)
    return tmp_path


# ---- properties ------------------------------------------------------------


def test_bit_width():
    assert PortConfig(name="p", width=12).bit_width == 12
    assert PortConfig(name="p", packed_dims=[4, 8]).bit_width == 32
    assert PortConfig(name="p", struct=HDR).bit_width == 9


def test_sv_type():
    assert PortConfig(name="m", packed_dims=[4, 8]).sv_type == "bit [3:0][7:0]"
    assert PortConfig(name="hdr", struct=HDR).sv_type == "hdr_t"
    assert PortConfig(name="p", packed_dims=[3]).sv_type == "bit [2:0]"


# ---- generated transaction + interface -------------------------------------


def test_struct_typedef_and_field(tmp_path):
    txt = (
        _gen(tmp_path, [PortConfig(name="hdr", struct=HDR)]) / "a_seq_item.svh"
    ).read_text()
    assert "typedef struct packed {" in txt
    assert "bit [7:0] tag;" in txt
    assert "bit en;" in txt
    assert "} hdr_t;" in txt
    assert "rand hdr_t hdr;" in txt


def test_packed_array_field(tmp_path):
    txt = (
        _gen(tmp_path, [PortConfig(name="lanes", packed_dims=[4, 8])])
        / "a_seq_item.svh"
    ).read_text()
    assert "rand bit [3:0][7:0] lanes;" in txt
    assert "typedef" not in txt  # a packed array needs no typedef


def test_interface_uses_total_bit_width(tmp_path):
    p = _gen(
        tmp_path,
        [
            PortConfig(name="hdr", struct=HDR),
            PortConfig(name="lanes", packed_dims=[4, 8]),
        ],
    )
    iface = (p / "a_if.sv").read_text()
    assert "logic [8:0] hdr;" in iface  # 8 + 1 struct bits
    assert "logic [31:0] lanes;" in iface  # 4 * 8 packed-array bits


def test_scalar_port_byte_identical(tmp_path):
    # a plain port still renders the legacy scalar form (bit_width == width)
    txt = (
        _gen(tmp_path, [PortConfig(name="x", width=8)]) / "a_seq_item.svh"
    ).read_text()
    assert "rand bit [7:0] x;" in txt


# ---- nested / composite struct members -------------------------------------

NESTED = PortConfig(
    name="hdr",
    struct=[
        StructMember(
            name="tag",
            struct=[
                StructMember(name="cls", width=4),
                StructMember(name="id", width=4),
            ],
        ),
        StructMember(name="lanes", packed_dims=[2, 8]),
        StructMember(name="en", width=1),
    ],
)


def test_nested_member_bit_width():
    assert NESTED.bit_width == 8 + 16 + 1  # tag(4+4) + lanes(2*8) + en
    assert NESTED.struct[0].bit_width == 8  # nested tag struct
    assert NESTED.struct[1].bit_width == 16  # packed-array member


def test_nested_struct_emits_named_typedefs(tmp_path):
    txt = (_gen(tmp_path, [NESTED]) / "a_seq_item.svh").read_text()
    # innermost typedef first, referenced by name in the outer struct
    assert "} hdr_tag_t;" in txt
    assert "hdr_tag_t tag;" in txt
    assert "bit [1:0][7:0] lanes;" in txt  # packed-array member, inline
    assert "} hdr_t;" in txt
    assert "rand hdr_t hdr;" in txt
    # named typedef precedes its use (verible: no anonymous structs)
    assert txt.index("} hdr_tag_t;") < txt.index("hdr_tag_t tag;")


def test_struct_typedefs_property():
    tds = NESTED.struct_typedefs
    assert [t["name"] for t in tds] == ["hdr_tag_t", "hdr_t"]  # innermost first


def test_nested_member_validation():
    with pytest.raises(Exception, match="duplicate nested member"):
        StructMember(name="t", struct=[StructMember(name="x"), StructMember(name="x")])
    with pytest.raises(Exception, match="at most one of packed_dims/struct/enum"):
        StructMember(name="t", packed_dims=[2], struct=[StructMember(name="x")])
    with pytest.raises(Exception, match="do not set 'width'"):
        StructMember(name="t", width=4, struct=[StructMember(name="x")])


# ---- enum struct members ---------------------------------------------------

ENUM_HDR = PortConfig(
    name="hdr",
    struct=[
        StructMember(name="cls", width=2, enum={"STD": 0, "EXT": 1, "MGMT": 2}),
        StructMember(name="id", width=6),
    ],
)


def test_enum_member_bit_width():
    assert ENUM_HDR.bit_width == 8  # 2-bit enum + 6
    assert ENUM_HDR.struct[0].bit_width == 2  # enum member uses its width


def test_enum_member_emits_named_typedef_before_struct(tmp_path):
    txt = (_gen(tmp_path, [ENUM_HDR]) / "a_seq_item.svh").read_text()
    assert "typedef enum logic [1:0] {" in txt
    assert "MGMT = 2'd2" in txt
    assert "} hdr_cls_e;" in txt
    assert "hdr_cls_e cls;" in txt  # member references the enum typedef by name
    # the enum typedef precedes the struct that uses it
    assert txt.index("} hdr_cls_e;") < txt.index("hdr_cls_e cls;")


def test_enum_member_typedefs_property():
    tds = ENUM_HDR.struct_typedefs
    assert tds[0]["kind"] == "enum"
    assert tds[0]["name"] == "hdr_cls_e"
    assert tds[-1]["kind"] == "struct" and tds[-1]["name"] == "hdr_t"


def test_enum_member_validation():
    with pytest.raises(Exception, match="at most one of packed_dims/struct/enum"):
        StructMember(name="m", enum={"A": 0}, struct=[StructMember(name="x")])
    with pytest.raises(Exception, match="does not fit"):
        StructMember(name="m", width=2, enum={"A": 0, "B": 9})  # 9 > 3
    with pytest.raises(Exception, match="must be unique"):
        StructMember(name="m", width=4, enum={"A": 0, "B": 0})


def test_enum_member_label_must_be_identifier():
    with pytest.raises(Exception, match="legal SystemVerilog identifier"):
        StructMember(name="m", width=4, enum={"2bad": 0})


def test_enum_member_typedef_collides_with_port_enum_rejected():
    # port 'hdr_cls' (enum -> hdr_cls_e) and port 'hdr'.member 'cls' (enum ->
    # hdr_cls_e) share the tb_pkg scope -> must be caught at config time
    with pytest.raises(Exception, match="collides"):
        _cfg(
            [
                PortConfig(name="hdr_cls", width=2, enum={"A": 0, "B": 1}),
                PortConfig(
                    name="hdr",
                    struct=[StructMember(name="cls", width=2, enum={"X": 0, "Y": 1})],
                ),
            ]
        )


def test_typedef_name_collision_rejected():
    # underscores in names let distinct paths flatten to the same typedef name:
    # member 'b_c' and member 'b' -> 'c' both produce 'a_b_c_t'
    with pytest.raises(Exception, match="collides"):
        _cfg(
            [
                PortConfig(
                    name="a",
                    struct=[
                        StructMember(name="b_c", struct=[StructMember(name="x")]),
                        StructMember(
                            name="b",
                            struct=[
                                StructMember(name="c", struct=[StructMember(name="y")])
                            ],
                        ),
                    ],
                )
            ]
        )


def test_cross_port_typedef_collision_rejected():
    # port 'a' member 'b_c' and port 'a_b' member 'c' both flatten to 'a_b_c_t'
    with pytest.raises(Exception, match="collides"):
        _cfg(
            [
                PortConfig(
                    name="a",
                    struct=[StructMember(name="b_c", struct=[StructMember(name="x")])],
                ),
                PortConfig(
                    name="a_b",
                    struct=[StructMember(name="c", struct=[StructMember(name="y")])],
                ),
            ]
        )


# ---- DPI (K0) interaction --------------------------------------------------


def test_packed_struct_marshals_in_dpi_when_small(tmp_path):
    # a 9-bit struct is <=64 bits -> a single DPI scalar (shortint)
    Generator(
        _cfg(
            [PortConfig(name="hdr", struct=HDR)],
            reference_model=ReferenceModelConfig(language="c"),
        )
    ).generate_all(tmp_path)
    bridge = (tmp_path / "d_reference_model.svh").read_text()
    assert "shortint hdr" in bridge  # bit_width 9 -> shortint DPI arg


def test_wide_packed_field_rejected_on_dpi():
    # packed_dims [4, 32] = 128 bits > 64 -> rejected on the DPI-C path
    with pytest.raises(Exception, match="128 bits|≤64-bit|<=64"):
        _cfg(
            [PortConfig(name="big", packed_dims=[4, 32])],
            reference_model=ReferenceModelConfig(language="c"),
        )


# ---- validation ------------------------------------------------------------


def test_struct_member_validation():
    with pytest.raises(Exception, match="legal SystemVerilog identifier"):
        StructMember(name="2bad")
    with pytest.raises(Exception, match="width must be >= 1"):
        StructMember(name="ok", width=0)


def test_type_specifiers_mutually_exclusive():
    with pytest.raises(Exception, match="at most one type specifier"):
        PortConfig(name="p", struct=HDR, enum={"A": 0})
    with pytest.raises(Exception, match="at most one type specifier"):
        PortConfig(name="p", packed_dims=[4, 8], type="my_t")


def test_packed_dims_must_be_positive():
    with pytest.raises(Exception, match="dimensions >= 1"):
        PortConfig(name="p", packed_dims=[4, 0])
    with pytest.raises(Exception, match="non-empty"):
        PortConfig(name="p", packed_dims=[])


def test_struct_needs_members():
    with pytest.raises(Exception, match="at least one member"):
        PortConfig(name="p", struct=[])


def test_explicit_width_with_composite_rejected():
    with pytest.raises(Exception, match="do not set 'width'"):
        PortConfig(name="p", width=8, struct=HDR)
    with pytest.raises(Exception, match="do not set 'width'"):
        PortConfig(name="p", width=8, packed_dims=[4, 8])


def test_composite_in_dpi_input_is_cast(tmp_path):
    # a composite input arg must be CAST to the DPI scalar type in the bridge call
    Generator(
        _cfg(
            [PortConfig(name="hdr", struct=HDR)],
            reference_model=ReferenceModelConfig(language="c"),
        )
    ).generate_all(tmp_path)
    bridge = (tmp_path / "d_reference_model.svh").read_text()
    assert "shortint'(t.hdr)" in bridge  # bit_width 9 -> cast to shortint in the call


def test_struct_duplicate_member_rejected():
    with pytest.raises(Exception, match="duplicate struct member"):
        PortConfig(name="p", struct=[StructMember(name="x"), StructMember(name="x")])


def test_incrementing_on_packed_field_rejected():
    # the incrementing-needs-plain-field check fires at agent construction
    with pytest.raises(Exception, match="incrementing"):
        _agent(
            [PortConfig(name="lanes", packed_dims=[4, 8])],
            sequences=[SequenceConfig(name="s", kind="incrementing", field="lanes")],
        )
