"""Pydantic v2 data models for QuickUVM configuration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# A pragmatic subset of SystemVerilog reserved words a user might accidentally use
# as a coverage bin name. Not exhaustive (IEEE 1800 has ~250); the identifier-format
# check below catches the rest of the common mistakes (spaces, hyphens, leading digit).
_SV_KEYWORDS = frozenset(
    {
        "begin",
        "end",
        "bit",
        "logic",
        "reg",
        "wire",
        "byte",
        "int",
        "integer",
        "shortint",
        "longint",
        "real",
        "shortreal",
        "time",
        "string",
        "enum",
        "struct",
        "union",
        "signed",
        "unsigned",
        "void",
        "type",
        "typedef",
        "if",
        "else",
        "case",
        "casex",
        "casez",
        "for",
        "while",
        "do",
        "repeat",
        "foreach",
        "return",
        "break",
        "continue",
        "default",
        "with",
        "inside",
        "bins",
        "illegal_bins",
        "ignore_bins",
        "wildcard",
        "cross",
        "coverpoint",
        "covergroup",
        "option",
        "iff",
        "class",
        "module",
        "function",
        "task",
    }
)
_SV_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _check_sv_identifier(name: str, what: str) -> None:
    """Raise unless `name` is a legal, non-reserved SystemVerilog identifier."""
    if not _SV_IDENT_RE.match(name):
        raise ValueError(
            f"{what} '{name}' is not a legal SystemVerilog identifier "
            f"(letters/digits/underscore, not starting with a digit)."
        )
    if name in _SV_KEYWORDS:
        raise ValueError(
            f"{what} '{name}' is a SystemVerilog reserved word — choose another name."
        )


class StructMember(BaseModel):
    """One field of a packed struct (S1).

    A plain integral member (`width`), a packed array (`packed_dims`), a NESTED
    packed struct (`struct`, recursive), or an `enum` (a generated `<path>_e`
    typedef using `width` as the encoding width). Composite/enum members are
    emitted as NAMED typedefs (see `_collect_struct_typedefs`).
    """

    name: str
    width: int = 1
    packed_dims: list[int] | None = None
    struct: list[StructMember] | None = None
    enum: dict[str, int] | None = None

    @model_validator(mode="after")
    def _check(self) -> StructMember:
        _check_sv_identifier(self.name, "struct member name")
        specs = [
            k
            for k, v in (
                ("packed_dims", self.packed_dims),
                ("struct", self.struct),
                ("enum", self.enum),
            )
            if v
        ]
        if len(specs) > 1:
            raise ValueError(
                f"struct member '{self.name}': set at most one of "
                f"packed_dims/struct/enum (got {specs})."
            )
        if self.packed_dims is not None and (
            not self.packed_dims or any(d < 1 for d in self.packed_dims)
        ):
            raise ValueError(
                f"struct member '{self.name}': packed_dims must be a non-empty list "
                f"of dimensions >= 1 (got {self.packed_dims})."
            )
        if self.struct is not None:
            if not self.struct:
                raise ValueError(
                    f"struct member '{self.name}': struct must declare at least one "
                    f"member."
                )
            seen: set[str] = set()
            for m in self.struct:
                if m.name in seen:
                    raise ValueError(
                        f"struct member '{self.name}': duplicate nested member "
                        f"'{m.name}'."
                    )
                seen.add(m.name)
        if self.enum is not None:
            if not self.enum:
                raise ValueError(
                    f"struct member '{self.name}': enum must have at least one value."
                )
            hi = (1 << self.width) - 1
            seen_v: dict[int, str] = {}
            for label, val in self.enum.items():
                _check_sv_identifier(label, f"struct member '{self.name}' enum label")
                if not (0 <= val <= hi):
                    raise ValueError(
                        f"struct member '{self.name}': enum value {label}={val} does "
                        f"not fit in {self.width} bit(s) (legal range 0..{hi})."
                    )
                if val in seen_v:
                    raise ValueError(
                        f"struct member '{self.name}': enum values must be unique — "
                        f"'{label}' and '{seen_v[val]}' both = {val}."
                    )
                seen_v[val] = label
        # packed_dims/struct DERIVE the width; enum and plain members USE `width`.
        if (self.packed_dims or self.struct) and self.width != 1:
            raise ValueError(
                f"struct member '{self.name}': do not set 'width' alongside "
                f"packed_dims/struct (the width is derived)."
            )
        if self.width < 1:
            raise ValueError(f"struct member '{self.name}': width must be >= 1.")
        return self

    @property
    def bit_width(self) -> int:
        """Total bits this member occupies (composite → derived, recursive)."""
        if self.packed_dims:
            w = 1
            for d in self.packed_dims:
                w *= d
            return w
        if self.struct:
            return sum(m.bit_width for m in self.struct)
        return self.width

    @property
    def sv_decl(self) -> str:
        """The member declaration body, e.g. `bit [7:0] addr` (no trailing ;).

        Composite members render inline and recursively: a packed array as
        `bit [d-1:0]..[..] name`, a nested struct as `struct packed { .. } name`.
        """
        if self.struct:
            inner = " ".join(f"{m.sv_decl};" for m in self.struct)
            return f"struct packed {{ {inner} }} {self.name}"
        if self.packed_dims:
            dims = "".join(f"[{d - 1}:0]" for d in self.packed_dims)
            return f"bit {dims} {self.name}"
        span = f"[{self.width - 1}:0] " if self.width > 1 else ""
        return f"bit {span}{self.name}"


def _collect_struct_typedefs(members: list[StructMember], prefix: str) -> list[dict]:
    """Depth-first NAMED typedefs for a (possibly nested) packed struct.

    Returns typedef dicts in dependency order (a member's typedef precedes the
    struct that references it); the last entry is the ``<prefix>_t`` struct.
    Each dict is tagged ``kind``: ``"struct"`` (``{kind, name, decls}``) or
    ``"enum"`` (``{kind, name, width, labels}``). A nested-struct member yields a
    ``<prefix>_<member>_t`` typedef and an enum member a ``<prefix>_<member>_e``
    one, both referenced by name; plain/array members use their inline
    ``sv_decl``. Named (not anonymous) so verible stays clean.
    """
    out: list[dict] = []
    decls: list[str] = []
    for m in members:
        if m.struct:
            out += _collect_struct_typedefs(m.struct, f"{prefix}_{m.name}")
            decls.append(f"{prefix}_{m.name}_t {m.name}")
        elif m.enum:
            nm = f"{prefix}_{m.name}_e"
            out.append({"kind": "enum", "name": nm, "width": m.width, "labels": m.enum})
            decls.append(f"{nm} {m.name}")
        else:
            decls.append(m.sv_decl)
    out.append({"kind": "struct", "name": f"{prefix}_t", "decls": decls})
    return out


class PortConfig(BaseModel):
    name: str
    width: int = 1
    # C3 — parameterized width: this scalar port's width is the named agent parameter
    # (e.g. width_param: W -> `logic [W-1:0]`). Scalar only (no enum/struct/packed).
    width_param: str | None = None
    randomize: bool = True  # only meaningful for input ports
    # S1 — rand_mode: when false the field is still declared `rand` (so it CAN be
    # randomized) but its rand_mode is disabled by default in the transaction's
    # new() — it holds its value through randomize() until a sequence/test re-enables
    # it via `tr.<field>.rand_mode(1)`. Only meaningful on a rand input port (a
    # per-field constraint on it is rejected). NOTE: while disabled the field is a
    # fixed state value, so a transaction-level `constraints:` entry referencing it
    # solves against that held value. (No equivalent on the var-length `fields:` yet.)
    rand_mode: bool = True
    # S1 — typed fields + constraints (all opt-in; a plain field is byte-identical).
    # BLACK BOX by default: declare named values and QuickUVM generates the
    # testbench's OWN enum (<name>_e) for this field, which self-constrains to its
    # legal values. The TB encodes the spec independently of the DUT's types.
    enum: dict[str, int] | None = None  # {NAME: value} -> typedef enum { NAME=value }
    # WHITE BOX escape hatch (powerful when needed): reference an EXTERNAL SV type
    # (e.g. a DUT/spec package type). The package must be compiled (present in the
    # filelist); a fully-qualified `pkg::type` works as-is, or add the package to
    # project.imports to also use its names unqualified in tb_pkg.
    type: str | None = None
    # Packed composite fields (still interface wires, fixed-width). A multi-dim
    # packed array `bit [d0-1:0]..[dn-1:0]` (packed_dims = [d0,..,dn]) or a packed
    # struct typedef (`struct`). The interface carries the raw bits; the
    # transaction declares the typed field. Mutually exclusive with enum/type.
    packed_dims: list[int] | None = None
    struct: list[StructMember] | None = None
    # SystemVerilog constraint expression for this field, emitted in a transaction
    # constraint block (e.g. "a != 0", "amt inside {[0:31]}", "a < b").
    constraint: str | None = None

    @model_validator(mode="after")
    def _check_field_type(self) -> PortConfig:
        set_specs = [
            k
            for k, v in (
                ("enum", self.enum),
                ("type", self.type),
                ("packed_dims", self.packed_dims),
                ("struct", self.struct),
            )
            if v
        ]
        if len(set_specs) > 1:
            raise ValueError(
                f"port '{self.name}': set at most one type specifier "
                f"(got {set_specs}) — enum/type/packed_dims/struct are exclusive."
            )
        if self.packed_dims is not None and (
            not self.packed_dims or any(d < 1 for d in self.packed_dims)
        ):
            raise ValueError(
                f"port '{self.name}': packed_dims must be a non-empty list of "
                f"dimensions >= 1 (got {self.packed_dims})."
            )
        if self.struct is not None:
            if not self.struct:
                raise ValueError(
                    f"port '{self.name}': struct must declare at least one member."
                )
            seen: set[str] = set()
            for m in self.struct:
                if m.name in seen:
                    raise ValueError(
                        f"port '{self.name}': duplicate struct member '{m.name}'."
                    )
                seen.add(m.name)
        if (self.packed_dims or self.struct) and self.width != 1:
            raise ValueError(
                f"port '{self.name}': do not set 'width' alongside packed_dims/struct "
                f"— the total bit width is derived from the composite (got width="
                f"{self.width})."
            )
        # C3 — a parameterized-width port is a plain scalar (the width is symbolic).
        if self.width_param is not None:
            _check_sv_identifier(self.width_param, f"port '{self.name}' width_param")
            if self.enum or self.type or self.packed_dims or self.struct:
                raise ValueError(
                    f"port '{self.name}': width_param is only for a scalar port "
                    f"(not enum/type/packed_dims/struct)."
                )
            if self.width != 1:
                raise ValueError(
                    f"port '{self.name}': set width_param OR width, not both."
                )
        return self

    @model_validator(mode="after")
    def _check_enum_values(self) -> PortConfig:
        """Fail closed on enum mistakes that would emit illegal SystemVerilog.

        The typedef renders each value as `<width>'d<value>`, so values must be
        non-negative, fit in `width` bits, and be unique — otherwise SV truncates
        or rejects the enum (a duplicate-value or `'d-1` compile error).
        """
        if self.enum is None:
            return self
        if not self.enum:
            raise ValueError(
                f"port '{self.name}': enum must declare at least one value."
            )
        hi = (1 << self.width) - 1
        seen: dict[int, str] = {}
        for label, val in self.enum.items():
            _check_sv_identifier(label, f"port '{self.name}' enum label")
            if not (0 <= val <= hi):
                raise ValueError(
                    f"port '{self.name}': enum value {label}={val} does not fit in "
                    f"{self.width} bit(s) (legal range 0..{hi})."
                )
            if val in seen:
                raise ValueError(
                    f"port '{self.name}': enum values must be unique — '{label}' and "
                    f"'{seen[val]}' both = {val}."
                )
            seen[val] = label
        return self

    @property
    def is_typed(self) -> bool:
        """True if the field declares a non-scalar SV type (enum/struct/array/ext)."""
        return bool(self.enum or self.type or self.packed_dims or self.struct)

    @property
    def bit_width(self) -> int:
        """Total bits the field occupies on the wire (packed/struct → derived)."""
        if self.packed_dims:
            w = 1
            for d in self.packed_dims:
                w *= d
            return w
        if self.struct:
            return sum(m.bit_width for m in self.struct)
        return self.width

    @property
    def sv_span(self) -> str:
        """Declaration span, e.g. ``[7:0] `` (with a trailing space) or ``[W-1:0] ``
        for a parameterized width (C3); empty for a 1-bit scalar. Used for the raw
        interface signal and the scalar transaction field."""
        if self.width_param:
            return f"[{self.width_param}-1:0] "
        w = self.bit_width
        return f"[{w - 1}:0] " if w > 1 else ""

    @property
    def sv_type(self) -> str:
        """The SystemVerilog type for this field's declaration."""
        if self.enum:
            return f"{self.name}_e"
        if self.type:
            return self.type
        if self.struct:
            return f"{self.name}_t"
        if self.packed_dims:
            return "bit " + "".join(f"[{d - 1}:0]" for d in self.packed_dims)
        return f"bit [{self.width - 1}:0]" if self.width > 1 else "bit"

    @property
    def struct_typedefs(self) -> list[dict]:
        """Named packed-struct typedefs to emit (innermost first) for a struct port.

        Each NESTED struct becomes its own `<port>_<path>_t` typedef — verible
        requires named structs — and a member references the nested typedef by
        name. Returns dicts `{name, decls}`; empty for a non-struct port.
        """
        if not self.struct:
            return []
        return _collect_struct_typedefs(self.struct, self.name)

    @property
    def dpi_sv_type(self) -> str:
        """SV scalar type for this field as a DPI-C argument (by width, K0)."""
        w = self.bit_width
        return (
            "byte"
            if w <= 8
            else "shortint"
            if w <= 16
            else "int"
            if w <= 32
            else "longint"
        )

    @property
    def dpi_c_type(self) -> str:
        """C scalar type matching dpi_sv_type (K0)."""
        w = self.bit_width
        return (
            "char"
            if w <= 8
            else "short"
            if w <= 16
            else "int"
            if w <= 32
            else "long long"
        )


class FieldConfig(BaseModel):
    """A transaction-only field (S1): variable-length data that is NOT an
    interface wire — a dynamic array or queue serialized by user pragma code in
    the driver/monitor. QuickUVM owns its declaration, randomization, field
    automation and constraints; the bus (de)serialization stays user code
    ("skeleton, not magic"). Opt-in: an agent with no `fields` is byte-identical.
    """

    name: str
    element_width: int = 8  # width of each element, e.g. 8 -> bit [7:0] x[]
    kind: Literal["dynamic", "queue"] = "dynamic"  # x[]  vs  x[$]
    randomize: bool = True
    # Sane default size bound so an unconstrained `rand` array can't randomize to a
    # runaway size; widen/narrow via these. Set bound_size:false to suppress the
    # auto-bound entirely and own sizing through `constraints:` (avoids a silent
    # contradiction between the implicit bound and a user size relation).
    min_size: int = 0
    max_size: int = 64
    bound_size: bool = True

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        _check_sv_identifier(v, "field name")
        return v

    @model_validator(mode="after")
    def _check_bounds(self) -> FieldConfig:
        if self.element_width < 1:
            raise ValueError(f"field '{self.name}': element_width must be >= 1.")
        if self.min_size < 0:
            raise ValueError(f"field '{self.name}': min_size must be >= 0.")
        floor = max(1, self.min_size)
        if self.max_size < floor:
            raise ValueError(
                f"field '{self.name}': max_size ({self.max_size}) must be >= "
                f"{floor} (max of 1 and min_size)."
            )
        return self

    @property
    def sv_element_type(self) -> str:
        """SV element type for the array/queue declaration."""
        return f"bit [{self.element_width - 1}:0]" if self.element_width > 1 else "bit"

    @property
    def sv_decl_suffix(self) -> str:
        """`[$]` for a queue, `[]` for a dynamic array."""
        return "[$]" if self.kind == "queue" else "[]"


PortMap = dict[Literal["inputs", "outputs"], list[PortConfig]]


def _default_ports() -> PortMap:
    return {"inputs": [], "outputs": []}


class SequenceConfig(BaseModel):
    """One generated sequence in an agent's library (S2).

    Opt-in: an agent with no `sequences` keeps only the legacy `<agent>_sequence`
    (byte-identical). `random` and `incrementing` generate working bodies;
    `directed`/`reset`/`error` generate a skeleton with a pragma body for the user.
    """

    name: str
    kind: Literal["random", "incrementing", "directed", "reset", "error", "nested"] = (
        "random"
    )
    count: int = 100
    field: str | None = None  # the input field to step — required by 'incrementing'
    # 'nested' (sequence-of-sequences): sibling library sequences started in order
    # on this sequence's sequencer. Each step must be a declared, non-nested
    # sequence of the same agent (validated in AgentConfig).
    steps: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        # name becomes `class <name>` and file <name>.svh — must be a legal identifier
        _check_sv_identifier(v, "sequence name")
        return v

    @model_validator(mode="after")
    def _check_kind(self) -> SequenceConfig:
        if self.kind == "incrementing" and not self.field:
            raise ValueError(
                f"sequence '{self.name}': kind 'incrementing' requires a 'field' to "
                f"step."
            )
        if self.field and self.kind != "incrementing":
            raise ValueError(
                f"sequence '{self.name}': 'field' only applies to kind "
                f"'incrementing' (got '{self.kind}')."
            )
        if self.kind == "nested" and not self.steps:
            raise ValueError(
                f"sequence '{self.name}': kind 'nested' requires a non-empty 'steps' "
                f"list of sibling sequences to run."
            )
        if self.kind != "nested" and self.steps:
            raise ValueError(
                f"sequence '{self.name}': 'steps' only applies to kind 'nested' "
                f"(got '{self.kind}')."
            )
        if self.count < 1:
            raise ValueError(f"sequence '{self.name}': count must be >= 1.")
        return self


class TestSeqSel(BaseModel):
    """A test's selection of a single agent-library sequence to run (S2).

    `count` (optional) overrides the selected sequence's item count for this test
    — the generated sequence exposes `count` as a settable member.
    """

    agent: str
    name: str
    count: int | None = None

    @model_validator(mode="after")
    def _check(self) -> TestSeqSel:
        if self.count is not None and self.count < 1:
            raise ValueError(
                f"test sequence selector '{self.name}': count must be >= 1 (got "
                f"{self.count})."
            )
        return self


class VseqStep(BaseModel):
    """One sub-sequence start inside a virtual sequence (C2)."""

    agent: str
    sequence: str  # a library sequence of `agent`, or its default <agent>_sequence


class VseqConfig(BaseModel):
    """A virtual sequence: coordinates per-agent sub-sequences via the vsqr (C2).

    `mode: sequential` starts the steps in order; `parallel` starts them in a
    fork…join. Each step targets an active agent's sequencer through the
    `env_vsqr` handles. Opt-in: declaring any `virtual_sequences` generates env_vsqr +
    env_vseq_base; absent ⇒ no virtual-sequence layer (byte-identical).
    """

    name: str
    mode: Literal["sequential", "parallel"] = "sequential"
    body: list[VseqStep] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        _check_sv_identifier(v, "vsequence name")
        return v

    @model_validator(mode="after")
    def _check_body(self) -> VseqConfig:
        if not self.body:
            raise ValueError(
                f"vsequence '{self.name}': declare at least one step in 'body'."
            )
        return self


class ParamConfig(BaseModel):
    """C3 — a SystemVerilog parameter on an agent VIP (e.g. a data width).

    Makes the agent's interface AND all its UVM classes parameterized `#(...)`, so
    the same VIP can be reused at different widths. Port widths reference it via
    `width_param`. Opt-in: an agent with no `parameters` is byte-identical.
    """

    name: str
    type: str = "int"
    default: int

    @model_validator(mode="after")
    def _check(self) -> ParamConfig:
        _check_sv_identifier(self.name, "parameter name")
        return self


class InstanceConfig(BaseModel):
    """C3 — one concrete instantiation of a parameterized agent VIP.

    Lets the SAME parameterized VIP be instantiated more than once in one bench
    at different parameter values (e.g. an 8-bit and a 16-bit datapath), each
    with its own interface, DUT, agent and scoreboard. `values` overrides the
    agent's parameter defaults for this instance. Opt-in: an agent with no
    `instances` keeps the legacy single-instantiation wiring (byte-identical).
    """

    name: str  # handle / scoreboard base for this instantiation (e.g. io8)
    values: dict[str, int] = Field(default_factory=dict)  # parameter name -> value

    @model_validator(mode="after")
    def _check(self) -> InstanceConfig:
        _check_sv_identifier(self.name, "instance name")
        return self


class AgentConfig(BaseModel):
    name: str
    interface: str
    sequence_item: str
    seq_item_style: Literal["manual", "field_macros"] = "manual"
    active: bool = True
    ports: PortMap = Field(default_factory=_default_ports)
    sequences: list[SequenceConfig] = Field(default_factory=list)  # S2 library
    # S1 — rich stimulus (opt-in, byte-identical when empty):
    fields: list[FieldConfig] = Field(default_factory=list)  # transaction-only data
    constraints: list[str] = Field(default_factory=list)  # transaction-level raw SV
    # A2 — monitor publish qualifier: when set, the monitor writes a transaction to
    # its analysis port only when this port (a valid/handshake signal) is non-zero.
    # Needed for valid-qualified streams (e.g. a two-stream req/rsp scoreboard) so
    # idle/pipeline-fill cycles don't enter the scoreboard. None → emit every cycle.
    emit_when: str | None = None
    # C3 — SystemVerilog parameters (opt-in, byte-identical when empty). Make the
    # interface + all UVM classes of this agent `#(...)`-parameterized.
    parameters: list[ParamConfig] = Field(default_factory=list)
    # C3 — instantiate this parameterized VIP more than once at different values
    # (opt-in, byte-identical when empty). Requires `parameters`.
    instances: list[InstanceConfig] = Field(default_factory=list)

    @property
    def param_decl(self) -> str:
        """The `#(...)` formal parameter declaration, e.g. ` #(parameter int W = 8)`;
        empty when the agent has no parameters (byte-identical)."""
        if not self.parameters:
            return ""
        inner = ", ".join(
            f"parameter {p.type} {p.name} = {p.default}" for p in self.parameters
        )
        return f" #({inner})"

    @property
    def param_args(self) -> str:
        """The `#(W)` formal reference (parameter names) used inside the parameterized
        classes when they name each other's types; empty when unparameterized."""
        if not self.parameters:
            return ""
        return "#(" + ", ".join(p.name for p in self.parameters) + ")"

    @property
    def param_args_values(self) -> str:
        """The `#(8)` concrete reference (default values) used by the env/top to
        instantiate the VIP; empty when unparameterized."""
        if not self.parameters:
            return ""
        return "#(" + ", ".join(str(p.default) for p in self.parameters) + ")"

    def instance_param_args_values(self, inst: InstanceConfig) -> str:
        """The `#(16)` concrete reference for one instance, overriding the
        parameter defaults with the instance's `values`; empty when the agent
        has no parameters."""
        if not self.parameters:
            return ""
        vals = [str(inst.values.get(p.name, p.default)) for p in self.parameters]
        return "#(" + ", ".join(vals) + ")"

    @property
    def input_ports(self) -> list[PortConfig]:
        return self.ports.get("inputs", [])

    @property
    def output_ports(self) -> list[PortConfig]:
        return self.ports.get("outputs", [])

    @property
    def all_ports(self) -> list[tuple[Literal["input", "output"], PortConfig]]:
        result: list[tuple[Literal["input", "output"], PortConfig]] = []
        for p in self.output_ports:
            result.append(("output", p))
        for p in self.input_ports:
            result.append(("input", p))
        return result

    @field_validator("name", "interface", "sequence_item")
    @classmethod
    def no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError(f"Name '{v}' must not contain spaces.")
        return v

    @model_validator(mode="after")
    def _check_constraints(self) -> AgentConfig:
        """A per-field constraint only makes sense on a randomizable field.

        Outputs are sampled from the DUT (non-rand), and a randomize=False input
        is non-rand too — a constraint there would either be dead or make every
        randomize() call fail at runtime, so reject it at config time.
        """
        for p in self.output_ports:
            if p.constraint:
                raise ValueError(
                    f"agent '{self.name}': output port '{p.name}' has a constraint, "
                    f"but outputs are sampled (non-rand). Constraints belong on rand "
                    f"inputs."
                )
            if not p.rand_mode:
                raise ValueError(
                    f"agent '{self.name}': output '{p.name}' sets rand_mode=false, but "
                    f"outputs are sampled (non-rand) — rand_mode only applies to rand "
                    f"input ports."
                )
        for p in self.input_ports:
            if p.constraint and not p.randomize:
                raise ValueError(
                    f"agent '{self.name}': input port '{p.name}' has a constraint but "
                    f"randomize=false (non-rand). Set randomize=true or drop it."
                )
            if not p.rand_mode and not p.randomize:
                raise ValueError(
                    f"agent '{self.name}': input port '{p.name}' sets rand_mode=false "
                    f"with randomize=false — a non-rand field has no rand_mode. Set "
                    f"randomize=true (rand, but disabled by default) or drop rand_mode."
                )
            if p.constraint and not p.rand_mode:
                raise ValueError(
                    f"agent '{self.name}': input port '{p.name}' has both a constraint "
                    f"and rand_mode=false — the field is held at its default, so the "
                    f"constraint is checked against that fixed value and may make "
                    f"randomize() fail. Drop the constraint or set rand_mode=true."
                )
        # A field name must be unique across inputs+outputs: the transaction
        # declares one member per field, and the DPI-C bridge (K0) emits one
        # formal per field — a name in both lists double-declares either way.
        overlap = {p.name for p in self.input_ports} & {
            p.name for p in self.output_ports
        }
        if overlap:
            raise ValueError(
                f"agent '{self.name}': field name(s) {sorted(overlap)} appear in both "
                f"inputs and outputs. Each field maps to one transaction member; use "
                f"distinct names (e.g. an '_in'/'_out' suffix)."
            )
        # S1 — transaction-only fields share the transaction namespace with ports;
        # names must be unique across ports+fields. Constraints must be non-empty.
        port_names = {p.name for p in self.input_ports} | {
            p.name for p in self.output_ports
        }
        fseen: set[str] = set()
        for f in self.fields:
            if f.name in port_names:
                raise ValueError(
                    f"agent '{self.name}': field '{f.name}' collides with a port of "
                    f"the same name — transaction-only fields and interface ports "
                    f"share the transaction namespace. Use a distinct name."
                )
            if f.name in fseen:
                raise ValueError(f"agent '{self.name}': duplicate field '{f.name}'.")
            fseen.add(f.name)
        for c in self.constraints:
            if not c.strip():
                raise ValueError(
                    f"agent '{self.name}': empty transaction constraint expression."
                )
        # A2 — the emit qualifier must name a 1-bit port the monitor samples: the
        # gate is `if (tr.<emit_when>)`, so a multi-bit field would be a surprising
        # reduction-OR rather than a clean valid/handshake test.
        if self.emit_when is not None:
            ew = next(
                (
                    p
                    for p in self.input_ports + self.output_ports
                    if p.name == self.emit_when
                ),
                None,
            )
            if ew is None:
                raise ValueError(
                    f"agent '{self.name}': emit_when='{self.emit_when}' is not a port "
                    f"of this agent (it must name a sampled valid/handshake signal)."
                )
            if ew.bit_width != 1:
                raise ValueError(
                    f"agent '{self.name}': emit_when='{self.emit_when}' is "
                    f"{ew.bit_width} bits — it must be a 1-bit valid/handshake signal "
                    f"(the monitor gates on `if (tr.{self.emit_when})`)."
                )
        seen: set[str] = set()
        ports_by_name = {p.name: p for p in self.input_ports}
        for s in self.sequences:
            if s.name in seen:
                raise ValueError(
                    f"agent '{self.name}': duplicate sequence name '{s.name}'."
                )
            seen.add(s.name)
            if s.name == f"{self.name}_seq":
                raise ValueError(
                    f"agent '{self.name}': sequence '{s.name}' collides with the "
                    f"generated default sequence — choose another name."
                )
            if s.kind == "incrementing":
                fld = ports_by_name.get(s.field or "")
                if fld is None or not fld.randomize:
                    raise ValueError(
                        f"agent '{self.name}': sequence '{s.name}' steps field "
                        f"'{s.field}', which is not a randomizable input port."
                    )
                if fld.is_typed:
                    raise ValueError(
                        f"agent '{self.name}': sequence '{s.name}' steps field "
                        f"'{s.field}', which is enum/typed/composite — 'incrementing' "
                        f"needs a plain integral field."
                    )
                if fld.constraint:
                    raise ValueError(
                        f"agent '{self.name}': sequence '{s.name}' steps field "
                        f"'{s.field}', which also has a per-field constraint — "
                        f"stepping and constraining the same field conflict."
                    )
        # 'nested' steps must reference declared, non-nested sibling sequences
        # (no self-reference / nesting-of-nested → no cycles).
        kind_by_name = {s.name: s.kind for s in self.sequences}
        for s in self.sequences:
            if s.kind != "nested":
                continue
            for step in s.steps:
                if step == s.name:
                    raise ValueError(
                        f"agent '{self.name}': nested sequence '{s.name}' lists "
                        f"itself as a step."
                    )
                if step not in kind_by_name:
                    raise ValueError(
                        f"agent '{self.name}': nested sequence '{s.name}' step "
                        f"'{step}' is not a declared sequence of this agent."
                    )
                if kind_by_name[step] == "nested":
                    raise ValueError(
                        f"agent '{self.name}': nested sequence '{s.name}' step "
                        f"'{step}' is itself nested — only non-nested sequences may "
                        f"be composed (avoids cycles)."
                    )
        # C3 — parameters: unique names; a port width_param must name a declared one.
        pnames = [p.name for p in self.parameters]
        if len(pnames) != len(set(pnames)):
            raise ValueError(f"agent '{self.name}': duplicate parameter name.")
        for p in self.input_ports + self.output_ports:
            if p.width_param is not None and p.width_param not in pnames:
                raise ValueError(
                    f"agent '{self.name}': port '{p.name}' width_param "
                    f"'{p.width_param}' is not a declared parameter of this agent "
                    f"(parameters: {pnames})."
                )
        # C3 — instances: each is a concrete instantiation of THIS parameterized VIP.
        if self.instances:
            if not self.parameters:
                raise ValueError(
                    f"agent '{self.name}': `instances` requires `parameters` — each "
                    f"instance overrides the agent's parameter values."
                )
            iseen: set[str] = set()
            for inst in self.instances:
                if inst.name in iseen:
                    raise ValueError(
                        f"agent '{self.name}': duplicate instance name '{inst.name}'."
                    )
                iseen.add(inst.name)
                for k in inst.values:
                    if k not in pnames:
                        raise ValueError(
                            f"agent '{self.name}': instance '{inst.name}' sets unknown "
                            f"parameter '{k}' (parameters: {pnames})."
                        )
        return self


class InstanceView:
    """A computed per-instantiation view for the env/top/scoreboard templates.

    There is one per `InstanceConfig` of a parameterized agent. It shares the
    agent's VIP class names (interface, sequence_item, cfg, agent) but carries
    instance-scoped handle/interface/DUT/vif/scoreboard names and this
    instance's concrete `#(..)` args, so N instances coexist without collision.
    Not user config — built by `ProjectConfig.instance_views`.
    """

    def __init__(self, agent: AgentConfig, name: str, pav: str):
        self.agent = agent
        self.name = name  # instance base name, e.g. io8
        self.pav = pav  # concrete args for this instance, e.g. #(16)

    @property
    def handle(self) -> str:
        return f"{self.name}_agnt"

    @property
    def cfg_field(self) -> str:
        return f"{self.name}_cfg"

    @property
    def if_inst(self) -> str:
        return f"{self.name}_if_inst"

    @property
    def dut_inst(self) -> str:
        return f"{self.name}_dut"

    @property
    def vif_key(self) -> str:
        return f"{self.name}_vif"

    @property
    def sb_handle(self) -> str:
        return f"{self.name}_sb"


class DutConfig(BaseModel):
    name: str
    clock: str = "clk"
    reset: str = "rst_n"
    reset_active_low: bool = True

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        # dut.name is the DUT module name AND the prefix for the bench-level class
        # names (<dut>_env, <dut>_scoreboard, <dut>_vseq, ...), so it must be a
        # legal SV identifier.
        _check_sv_identifier(v, "dut name")
        return v

    # Opt-in: the reset is driven EXTERNALLY (by a top-level reset generator),
    # not by the agent. When true, QuickUVM declares the reset as an interface
    # port, generates a `reset_generator` in top, and reset-gates the driver +
    # monitor (they hold off until reset deasserts). Leave false when the reset
    # is an agent input port (agent-driven) or handled in user pragma code.
    # Flipping true->false later removes the reset_generator pragma region, so
    # regeneration is fail-closed (re-run with --allow-drop to discard it).
    external_reset: bool = False
    # Opt-in: the DUT is purely COMBINATIONAL (no clock/reset of its own). The
    # generated clock is kept as a testbench cadence (one vector/cycle), but it
    # is NOT connected to the DUT; the DUT stub is always_comb; and the monitor
    # samples inputs AND outputs together (0-cycle latency) race-free through a
    # dedicated monitor clocking block. The cadence period (clock.period) must
    # exceed the DUT's combinational settling time.
    combinational: bool = False


class ClockConfig(BaseModel):
    period: int = 10
    unit: str = "ns"
    drive_offset_pct: int = 20  # percent of period to delay drive after posedge


class TestConfig(BaseModel):
    name: str
    num_items: int = 100
    # S2 — run a selected agent-library sequence instead of the default
    # <primary>_sequence. None ⇒ today's behavior (byte-identical).
    sequence: TestSeqSel | None = None
    # C2 — run a virtual sequence on the env's vsqr (coordinates >=2 agents).
    vseq: str | None = None

    @field_validator("name")
    @classmethod
    def no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError(f"Test name '{v}' must not contain spaces.")
        return v

    @model_validator(mode="after")
    def _check_stimulus(self) -> TestConfig:
        if self.sequence is not None and self.vseq is not None:
            raise ValueError(
                f"test '{self.name}': set either 'sequence' (single-agent) or 'vseq' "
                f"(virtual sequence), not both."
            )
        return self


class ScoreboardSpec(BaseModel):
    name: str = "sbd"
    source: str  # input/stimulus stream agent → predictor
    # A2 — two-stream topology: when set, this is the OUTPUT/response stream agent
    # whose monitored transactions are the scoreboard's "actual" (predict(source) is
    # compared against monitor). Omitted → single-stream (source feeds both the
    # predictor and the comparator, today's behavior). monitor != source.
    monitor: str | None = None
    # A2 — comparison strategy. 'in_order' (default): a FIFO pair matches expected
    # and actual in arrival order. 'out_of_order': a queue-per-key pool matches each
    # actual to the pending expected with the same `match_key` (a reordering DUT).
    match: Literal["in_order", "out_of_order"] = "in_order"
    match_key: str | None = None  # monitor-item field to key on; required iff OOO
    # A2 — latency window: max request→response latency in CLOCK CYCLES. When set,
    # the comparator flags (SB_LATENCY) a response that matches its request but
    # arrived later than this; a response that never arrives is caught by
    # SB_LEFTOVER. Out-of-order only (the pool it stamps lives there).
    max_latency: int | None = None

    @model_validator(mode="after")
    def _check_match(self) -> ScoreboardSpec:
        # The name appears in generated class names (<dut>_<name>_predictor, ...) when
        # there are >=2 scoreboards, so it must be a legal SV identifier.
        _check_sv_identifier(self.name, "scoreboard name")
        if self.match == "out_of_order":
            if self.monitor is None:
                raise ValueError(
                    f"scoreboard '{self.name}': match='out_of_order' requires a "
                    f"two-stream scoreboard (set 'monitor')."
                )
            if not self.match_key:
                raise ValueError(
                    f"scoreboard '{self.name}': match='out_of_order' requires "
                    f"'match_key' (the response field that tags each transaction)."
                )
        elif self.match_key is not None:
            raise ValueError(
                f"scoreboard '{self.name}': match_key is only used with "
                f"match='out_of_order'."
            )
        if self.max_latency is not None:
            if self.match != "out_of_order":
                raise ValueError(
                    f"scoreboard '{self.name}': max_latency is only supported with "
                    f"match='out_of_order'."
                )
            if self.max_latency < 1:
                raise ValueError(
                    f"scoreboard '{self.name}': max_latency must be >= 1 cycle."
                )
        return self


class AnalysisConfig(BaseModel):
    """Opt-in declarative analysis connectivity (C1, MVP per-agent routing).

    When omitted, the environment keeps the legacy single-stream wiring
    (one scoreboard + one coverage collector on the primary agent).
    """

    coverage: list[str] = Field(default_factory=list)  # agent names that get a cover
    scoreboards: list[ScoreboardSpec] = Field(default_factory=list)


class CoverageBin(BaseModel):
    """One named bin of a coverpoint — exactly one of value/range/values."""

    name: str
    value: int | None = None
    range: tuple[int, int] | None = None  # inclusive [lo, hi]
    values: list[int] | None = None

    @model_validator(mode="after")
    def _check_one(self) -> CoverageBin:
        _check_sv_identifier(self.name, "coverage bin name")
        n_set = sum(x is not None for x in (self.value, self.range, self.values))
        if n_set != 1:
            raise ValueError(
                f"coverage bin '{self.name}': set exactly one of 'value', 'range', "
                f"or 'values'."
            )
        if self.range is not None and self.range[0] > self.range[1]:
            raise ValueError(
                f"coverage bin '{self.name}': range low {self.range[0]} > high "
                f"{self.range[1]}."
            )
        if self.values is not None and not self.values:
            raise ValueError(f"coverage bin '{self.name}': 'values' must be non-empty.")
        return self

    def all_values(self) -> list[int]:
        """Every concrete value the bin references (for width range-checking)."""
        if self.value is not None:
            return [self.value]
        if self.range is not None:
            return [self.range[0], self.range[1]]
        return list(self.values or [])

    @property
    def sv_bin(self) -> str:
        """The SystemVerilog bin set-expression (the `{...}` content)."""
        if self.value is not None:
            return f"{{{self.value}}}"
        if self.range is not None:
            return f"{{[{self.range[0]}:{self.range[1]}]}}"
        return "{" + ", ".join(str(v) for v in (self.values or [])) + "}"


class TransitionBin(BaseModel):
    """A transition (temporal) bin — `bins <name> = (<seq>);` where `<seq>` is a
    SystemVerilog transition like `IDLE => BUSY` or `0 => 1 => 2`. The sequence is
    a light-validated raw expression (enum labels or integer values); QuickUVM only
    checks it names a legal bin and contains a `=>`.
    """

    name: str
    seq: str

    @model_validator(mode="after")
    def _check(self) -> TransitionBin:
        _check_sv_identifier(self.name, "transition bin name")
        states = [s.strip() for s in self.seq.split("=>")]
        if len(states) < 2 or any(not s for s in states):
            raise ValueError(
                f"transition bin '{self.name}': seq must be a transition "
                f"'a => b [=> c ...]' with non-empty states (got '{self.seq}')."
            )
        return self

    def int_endpoints(self) -> list[int]:
        """Integer-literal states in the sequence (for width/enum range-checking).

        Skipped entirely when the seq uses advanced transition syntax (`[* n]`,
        `[-> n]`, `[= n]`, ranges) — those brackets carry repetition counts, not
        values, so naive extraction would false-positive.
        """
        if "[" in self.seq:
            return []
        return [int(tok) for tok in re.findall(r"\b\d+\b", self.seq)]


class Coverpoint(BaseModel):
    field: str  # must name a port on the covered agent
    bins: list[CoverageBin] = Field(default_factory=list)
    # V1 closure — illegal_bins flag a hit as an error; ignore_bins exclude values
    # from the coverage denominator; transitions are temporal (a => b) bins. All
    # opt-in and orthogonal to `bins`; coexist with enum/wide auto-bins (only an
    # explicit `bins` declaration suppresses automatic bin creation).
    illegal_bins: list[CoverageBin] = Field(default_factory=list)
    ignore_bins: list[CoverageBin] = Field(default_factory=list)
    transitions: list[TransitionBin] = Field(default_factory=list)
    at_least: int | None = None  # per-coverpoint override of cg option.at_least
    # Cap the number of AUTO bins (`option.auto_bin_max`). Only for an auto-binned
    # coverpoint (no explicit `bins`/`transitions`) — and setting it lets a wide
    # plain field be auto-binned into N buckets instead of requiring explicit bins.
    auto_bin_max: int | None = None

    @property
    def all_bins(self) -> list[CoverageBin]:
        """Every value-form bin (normal + illegal + ignore), for width-checking."""
        return [*self.bins, *self.illegal_bins, *self.ignore_bins]

    @model_validator(mode="after")
    def _check_cp(self) -> Coverpoint:
        if self.at_least is not None and self.at_least < 1:
            raise ValueError(
                f"coverpoint '{self.field}': at_least must be >= 1 (got "
                f"{self.at_least})."
            )
        if self.auto_bin_max is not None:
            if self.auto_bin_max < 1:
                raise ValueError(
                    f"coverpoint '{self.field}': auto_bin_max must be >= 1 (got "
                    f"{self.auto_bin_max})."
                )
            if self.bins or self.transitions:
                raise ValueError(
                    f"coverpoint '{self.field}': auto_bin_max applies only to an "
                    f"auto-binned coverpoint — explicit bins/transitions suppress "
                    f"automatic bins, so it would have no effect."
                )
        # Bin names share one namespace across all four lists.
        seen: set[str] = set()
        names = (
            [b.name for b in self.bins]
            + [b.name for b in self.illegal_bins]
            + [b.name for b in self.ignore_bins]
            + [t.name for t in self.transitions]
        )
        for nm in names:
            if nm in seen:
                raise ValueError(
                    f"coverpoint '{self.field}': duplicate bin name '{nm}'."
                )
            seen.add(nm)
        return self


class CrossBin(BaseModel):
    """A `binsof`-based selection bin inside a cross (V1 closure).

    `select` is a raw SystemVerilog cross-bin select expression — e.g.
    `binsof(op_cp) intersect {ADD}` or `binsof(a_cp.zero) && binsof(op_cp)` —
    referencing coverpoints by their generated `<field>_cp` names. It is emitted
    verbatim on one line, so keep it short (≈80 chars) to stay within the 100-col
    verible line limit the CI enforces; split a complex selection across two bins.
    """

    name: str
    kind: Literal["bins", "ignore_bins", "illegal_bins"] = "bins"
    select: str

    @model_validator(mode="after")
    def _check(self) -> CrossBin:
        _check_sv_identifier(self.name, "cross bin name")
        if not self.select.strip():
            raise ValueError(f"cross bin '{self.name}': select expression is empty.")
        return self


class CrossSpec(BaseModel):
    """A cross of >=2 coverpoints with optional `binsof` bin selection (V1).

    The plain `crosses: [[a, b]]` list form is still accepted (no selection); use
    the object form `{fields: [a, b], bins: [...]}` to refine the cross. `name`
    overrides the auto-derived `<f1>_x_<f2>` cross name (needed if two crosses
    span the same fields).
    """

    fields: list[str]
    bins: list[CrossBin] = Field(default_factory=list)
    name: str | None = None

    @model_validator(mode="after")
    def _check(self) -> CrossSpec:
        if self.name is not None:
            _check_sv_identifier(self.name, "cross name")
        return self

    @property
    def cross_name(self) -> str:
        """The covergroup cross label — explicit `name` or `<f1>_x_<f2>`."""
        return self.name or "_x_".join(self.fields)


class CoverageModel(BaseModel):
    """Opt-in functional coverage model for one agent (V1).

    Generates a real covergroup (config-driven coverpoints + bins + crosses) in
    <agent>_cover, replacing the generic auto-bin stub. Sampled on the monitor's
    analysis write (no new plumbing). Black box: bins encode the spec's
    interesting values independently of the DUT's internals.
    """

    agent: str
    coverpoints: list[Coverpoint] = Field(default_factory=list)
    # A cross is either a plain list of coverpoint fields (no selection) or a
    # CrossSpec with optional binsof bins/ignore/illegal selection.
    crosses: list[list[str] | CrossSpec] = Field(default_factory=list)
    goal: int | None = None  # covergroup option.goal (closure target, percent 1..100)

    @property
    def crosses_normalized(self) -> list[CrossSpec]:
        """Every cross as a CrossSpec (a plain field-list → CrossSpec, no bins)."""
        return [
            c if isinstance(c, CrossSpec) else CrossSpec(fields=c) for c in self.crosses
        ]

    @model_validator(mode="after")
    def _check_shape(self) -> CoverageModel:
        if self.goal is not None and not (1 <= self.goal <= 100):
            raise ValueError(
                f"coverage_model for agent '{self.agent}': goal must be a percent in "
                f"1..100 (got {self.goal})."
            )
        if not self.coverpoints:
            raise ValueError(
                f"coverage_model for agent '{self.agent}': declare at least one "
                f"coverpoint."
            )
        cp_fields: set[str] = set()
        for cp in self.coverpoints:
            if cp.field in cp_fields:
                raise ValueError(
                    f"coverage_model for agent '{self.agent}': duplicate coverpoint "
                    f"for field '{cp.field}' (each field gets one coverpoint)."
                )
            cp_fields.add(cp.field)
        seen_cross: set[str] = set()
        for cr in self.crosses_normalized:
            if cr.cross_name in seen_cross:
                raise ValueError(
                    f"coverage_model for agent '{self.agent}': duplicate cross name "
                    f"'{cr.cross_name}' — two crosses over the same fields need a "
                    f"distinct `name`."
                )
            seen_cross.add(cr.cross_name)
            if len(cr.fields) < 2:
                raise ValueError(
                    f"coverage_model for agent '{self.agent}': a cross needs >= 2 "
                    f"fields, got {cr.fields}."
                )
            for f in cr.fields:
                if f not in cp_fields:
                    raise ValueError(
                        f"coverage_model for agent '{self.agent}': cross references "
                        f"'{f}', which is not a declared coverpoint."
                    )
            seen_cb: set[str] = set()
            for b in cr.bins:
                if b.name in seen_cb:
                    raise ValueError(
                        f"coverage_model for agent '{self.agent}': cross "
                        f"'{cr.cross_name}' has a duplicate bin name '{b.name}'."
                    )
                seen_cb.add(b.name)
        return self


class RegisterModelConfig(BaseModel):
    """Opt-in front-door register-model (RAL) integration (C4a).

    The uvm_reg_block itself is generated externally (e.g. by reggen/SystemRDL)
    and named here; QuickUVM generates the adapter skeleton, the env/test wiring
    (set_sequencer + optional explicit-prediction predictor) and an optional
    register test. The reg2bus/bus2reg protocol mapping is user code (pragmas).
    """

    package: str  # external uvm_reg package to import
    block: str  # uvm_reg_block subclass name
    map: str = "default_map"  # register map name within the block
    bus_agent: str  # agent whose sequencer drives front-door access
    adapter: str = "reg_adapter"  # generated uvm_reg_adapter class name
    use_predictor: bool = True  # explicit prediction via the bus agent's ap
    reg_test: bool = True  # generate a hw_reset/bit_bash register test
    # C5 — generate a separate runnable CSR test per kind, each running the matching
    # UVM built-in register/memory sequence on the RAL (data-path scoreboard off).
    # Each becomes a `<dut>_csr_<kind>_test`, run via +UVM_TESTNAME.
    csr_tests: list[Literal["hw_reset", "bit_bash", "rw", "mem_walk", "shared"]] = (
        Field(default_factory=list)
    )
    backdoor_root: str | None = None  # absolute HDL path to the regfile instance;
    # set to enable backdoor (model.add_hdl_path)
    reg_test_door: Literal["frontdoor", "backdoor"] = "frontdoor"
    frontdoor: str | None = None  # custom uvm_reg_frontdoor class to generate +
    # install on all registers (protocol body = pragma)

    # Handle names the env/base-test declare for the register model. A user-supplied
    # class name (adapter/block/frontdoor) equal to one of these would have its local
    # handle shadow the type, so `<name>::type_id::create` fails to bind (the original
    # reg_adapter/reg_adapter collision). Reject the whole class up front.
    _RESERVED_HANDLES: ClassVar[frozenset[str]] = frozenset(
        {"reg_model", "bus_adapter", "reg_predictor", "reg_fd"}
    )

    @model_validator(mode="after")
    def _check_backdoor(self) -> RegisterModelConfig:
        if self.reg_test_door == "backdoor" and not self.backdoor_root:
            raise ValueError(
                "register_model.reg_test_door='backdoor' requires backdoor_root "
                "(the HDL path to the regfile, e.g. 'top.dut_inst.regs_inst')."
            )
        if len(self.csr_tests) != len(set(self.csr_tests)):
            raise ValueError(
                f"register_model.csr_tests has duplicate kinds: {self.csr_tests}."
            )
        for fld in ("block", "adapter", "frontdoor"):
            val = getattr(self, fld)
            if val in self._RESERVED_HANDLES:
                raise ValueError(
                    f"register_model.{fld}='{val}' collides with a generated env "
                    f"handle of the same name (the handle would shadow the class). "
                    f"Rename it; reserved: {sorted(self._RESERVED_HANDLES)}."
                )
        return self

    @property
    def csr_test_specs(self) -> list[dict]:
        """Per-kind CSR test specs: {kind, seq} mapping each selected kind to its
        UVM built-in register/memory sequence."""
        seqs = {
            "hw_reset": "uvm_reg_hw_reset_seq",
            "bit_bash": "uvm_reg_bit_bash_seq",
            "rw": "uvm_reg_access_seq",
            "mem_walk": "uvm_mem_walk_seq",
            "shared": "uvm_reg_shared_access_seq",
        }
        return [{"kind": k, "seq": seqs[k]} for k in self.csr_tests]


class ReferenceModelConfig(BaseModel):
    """Configures the scoreboard's reference model / predictor (K0).

    `language: sv` (default) keeps the SV `predict()` body in
    `<dut>_reference_model.svh` (byte-identical). `language: c` generates a DPI-C
    seam instead: a fully-generated SV marshaling bridge + a `<dut>_reference_model.c`
    stub (the only file the user edits) whose `<dut>_predict` signature is derived
    from the primary agent's transaction fields.
    """

    language: Literal["sv", "c"] = "sv"


class ProjectMeta(BaseModel):
    name: str
    author: str = ""
    year: int = 2026
    uvm_version: Literal["1.1d", "1.2"] = "1.2"  # selects version-specific UVM APIs
    # Packages to import into tb_pkg (e.g. for PortConfig.type external references).
    # Prefer the black-box default (generated enums); use this only when the TB
    # genuinely must share a spec/DUT package.
    imports: list[str] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    project: ProjectMeta
    dut: DutConfig
    clock: ClockConfig = Field(default_factory=ClockConfig)
    agents: list[AgentConfig] = Field(default_factory=list)
    tests: list[TestConfig] = Field(default_factory=lambda: [TestConfig(name="test1")])
    analysis: AnalysisConfig | None = None
    register_model: RegisterModelConfig | None = None
    coverage_models: list[CoverageModel] = Field(default_factory=list)
    virtual_sequences: list[VseqConfig] = Field(default_factory=list)  # C2
    reference_model: ReferenceModelConfig = Field(default_factory=ReferenceModelConfig)
    # Sane default for multi-agent subsystems: with >=2 active agents and no explicit
    # virtual_sequences, auto-scaffold a vsqr + a default vseq that fires each agent's
    # base sequence (the "add a vsqr as a habit" convention). Set false to opt out.
    auto_virtual_sequences: bool = True
    auto_vseq_mode: Literal["parallel", "sequential"] = "parallel"
    # F2 — VIP packaging. 'flat' (default): one <dut>_tb_pkg with everything
    # (byte-identical). 'packaged': a standalone <agent>_pkg per agent, a
    # <dut>_env_pkg, and a <dut>_test_pkg, with per-package .f filelists — for
    # separate compilation and cross-project reuse of the agent VIP.
    layout: Literal["flat", "packaged"] = "flat"

    @model_validator(mode="after")
    def validate_agents(self) -> ProjectConfig:
        names = [a.name for a in self.agents]
        if len(names) != len(set(names)):
            raise ValueError("Agent names must be unique.")
        if not self.agents:
            raise ValueError("At least one agent must be defined.")
        agent_name_set = set(names)
        if self.analysis is not None:
            agent_names = set(names)
            for ag in self.analysis.coverage:
                if ag not in agent_names:
                    raise ValueError(
                        f"analysis.coverage references unknown agent '{ag}'."
                    )
            sb_names = [s.name for s in self.analysis.scoreboards]
            if len(sb_names) != len(set(sb_names)):
                raise ValueError("analysis.scoreboards names must be unique.")
            for s in self.analysis.scoreboards:
                if s.source not in agent_names:
                    raise ValueError(
                        f"analysis.scoreboards '{s.name}' references unknown "
                        f"source agent '{s.source}'."
                    )
                if s.monitor is not None and s.monitor not in agent_names:
                    raise ValueError(
                        f"analysis.scoreboards '{s.name}' references unknown "
                        f"monitor agent '{s.monitor}'."
                    )
                if s.monitor is not None and s.monitor == s.source:
                    raise ValueError(
                        f"analysis.scoreboards '{s.name}': monitor must differ from "
                        f"source (a two-stream scoreboard needs distinct in/out "
                        f"streams); omit monitor for a single-stream scoreboard."
                    )
                # match_key must name a field of the monitor (output) item, since
                # both the expected (predicted) and actual responses carry it; the
                # comparator keys on `longint'(<match_key>)`, so it must be a scalar
                # integral tag of at most 64 bits.
                if s.match_key is not None and s.monitor is not None:
                    mon = next(a for a in self.agents if a.name == s.monitor)
                    mk = next(
                        (
                            p
                            for p in mon.input_ports + mon.output_ports
                            if p.name == s.match_key
                        ),
                        None,
                    )
                    if mk is None:
                        raise ValueError(
                            f"analysis.scoreboards '{s.name}': match_key "
                            f"'{s.match_key}' is not a port of the monitor agent "
                            f"'{s.monitor}' (it must tag each response)."
                        )
                    if mk.struct is not None or mk.packed_dims is not None:
                        raise ValueError(
                            f"analysis.scoreboards '{s.name}': match_key "
                            f"'{s.match_key}' must be a scalar integral field, not a "
                            f"struct/packed array (it is cast to longint for keying)."
                        )
                    if mk.bit_width > 64:
                        raise ValueError(
                            f"analysis.scoreboards '{s.name}': match_key "
                            f"'{s.match_key}' is {mk.bit_width} bits; the key is a "
                            f"64-bit longint, so the tag must be <= 64 bits."
                        )
            # A two-stream scoreboard's predict() is SystemVerilog (DPI-C two-type
            # marshaling is not yet supported). With >=2 scoreboards each gets its
            # own typed predictor/comparator set (<dut>_<sbname>_*).
            two_stream = [s for s in self.analysis.scoreboards if s.monitor is not None]
            if two_stream and self.reference_model.language != "sv":
                raise ValueError(
                    "a two-stream scoreboard requires reference_model.language "
                    "'sv' (DPI-C two-type marshaling is not yet supported)."
                )
        if self.register_model is not None:
            if self.register_model.bus_agent not in {a.name for a in self.agents}:
                raise ValueError(
                    f"register_model.bus_agent references unknown agent "
                    f"'{self.register_model.bus_agent}'."
                )
        # C3 — multi-instantiation (`instances`) is a focused slice: one parameterized
        # agent, instantiated N times, each with its own interface/DUT/scoreboard.
        # Checked before the parameterized-agent guards so its message wins.
        if any(a.instances for a in self.agents):
            if len(self.agents) != 1:
                raise ValueError(
                    "agent `instances` are supported only in a single-agent bench "
                    "(this slice) — the sole agent's VIP is reused at each instance."
                )
            if self.analysis is not None:
                raise ValueError(
                    "agent `instances` + `analysis` is not supported yet (each "
                    "instance already gets its own generated scoreboard)."
                )
            if self.layout != "flat":
                raise ValueError(
                    "agent `instances` currently require the default `layout: flat` "
                    "(the packaged layout does not yet thread per-instance "
                    "scoreboards)."
                )
        # C3 — a parameterized agent is not yet wired through every path. Fail closed
        # on the combinations that would generate a concrete (non-parameterized) width.
        param_agents = {a.name for a in self.agents if a.parameters}
        if param_agents:
            if self.reference_model.language != "sv":
                raise ValueError(
                    "a parameterized agent requires reference_model.language 'sv' "
                    "(DPI-C marshaling needs concrete field widths)."
                )
            for cm in self.coverage_models:
                if cm.agent in param_agents:
                    raise ValueError(
                        f"coverage_models on the parameterized agent '{cm.agent}' are "
                        f"not supported yet (covergroups need concrete widths)."
                    )
            if self.analysis is not None:
                for ag in self.analysis.coverage:
                    if ag in param_agents:
                        raise ValueError(
                            f"a parameterized agent ('{ag}') in analysis.coverage is "
                            f"not supported yet."
                        )
            if self.effective_virtual_sequences:
                raise ValueError(
                    "parameterized agents + virtual sequences are not supported yet "
                    "(the vseq classes are not parameterized) — set "
                    "auto_virtual_sequences: false or avoid vseqs."
                )
            if (
                self.register_model is not None
                and self.register_model.bus_agent in param_agents
            ):
                raise ValueError(
                    f"a parameterized register_model.bus_agent "
                    f"('{self.register_model.bus_agent}') is not supported yet "
                    f"(the RAL adapter/predictor need a concrete transaction type)."
                )
        if self.dut.external_reset:
            if not self.dut.reset:
                raise ValueError(
                    "dut.external_reset requires dut.reset to name the reset signal."
                )
            if self.dut.reset == self.dut.clock:
                raise ValueError(
                    f"dut.external_reset: dut.reset '{self.dut.reset}' must differ "
                    f"from dut.clock (would create a duplicate interface port)."
                )
            port_names = {p.name for a in self.agents for _, p in a.all_ports}
            if self.dut.reset in port_names:
                raise ValueError(
                    f"dut.external_reset is set but dut.reset '{self.dut.reset}' is an "
                    f"agent port. An external reset must not also be an agent port — "
                    f"remove it from the agent ports or unset external_reset."
                )
        if self.dut.combinational and self.dut.external_reset:
            raise ValueError(
                "dut.combinational and dut.external_reset are mutually exclusive "
                "(a combinational DUT has no reset)."
            )
        # Which agents actually get a <agent>_cover instance in the env: the
        # listed agents when an analysis block is present, else just the primary.
        # A coverage model on any other agent would compile but never be sampled.
        covered_agents = (
            set(self.analysis.coverage) if self.analysis else {self.agents[0].name}
        )
        seen_cov: set[str] = set()
        for cm in self.coverage_models:
            if cm.agent not in agent_name_set:
                raise ValueError(
                    f"coverage_models references unknown agent '{cm.agent}'."
                )
            if cm.agent in seen_cov:
                raise ValueError(
                    f"coverage_models: duplicate model for agent '{cm.agent}'."
                )
            seen_cov.add(cm.agent)
            if cm.agent not in covered_agents:
                hint = (
                    f"add '{cm.agent}' to analysis.coverage"
                    if self.analysis
                    else f"only the primary agent '{self.agents[0].name}' is covered "
                    f"by default — add an analysis.coverage list to cover others"
                )
                raise ValueError(
                    f"coverage_model[{cm.agent}]: agent '{cm.agent}' has a coverage "
                    f"model but is not wired for coverage ({hint})."
                )
            agent = next(a for a in self.agents if a.name == cm.agent)
            port_by_name = {p.name: p for _, p in agent.all_ports}
            for cp in cm.coverpoints:
                if cp.field not in port_by_name:
                    raise ValueError(
                        f"coverage_model[{cm.agent}]: coverpoint field '{cp.field}' is "
                        f"not a port of agent '{cm.agent}'."
                    )
                port = port_by_name[cp.field]
                if (
                    not cp.bins
                    and not cp.transitions
                    and cp.auto_bin_max is None
                    and not port.enum
                    and port.bit_width > 1
                ):
                    raise ValueError(
                        f"coverage_model[{cm.agent}]: coverpoint '{cp.field}' "
                        f"({port.bit_width} bits) needs explicit bins/transitions or "
                        f"an auto_bin_max (auto-partition is only for enum/1-bit "
                        f"fields)."
                    )
                if cp.auto_bin_max is not None and port.enum:
                    raise ValueError(
                        f"coverage_model[{cm.agent}]: coverpoint '{cp.field}' sets "
                        f"auto_bin_max on an enum field, where auto bins are "
                        f"one-per-label — it has no effect (simulators ignore it). "
                        f"Drop it, or add explicit bins."
                    )
                hi = (1 << port.bit_width) - 1
                legal_enum = set(port.enum.values()) if port.enum else None
                # Every binned value (bins + illegal + ignore + integer transition
                # endpoints) must be storable by the coverpoint: a declared enum
                # label for an enum field (others are silently dropped by the
                # simulator, OBINRGE), or within the width range for a plain field.
                checks: list[tuple[int, str]] = []
                for b in cp.all_bins:
                    checks += [(v, f"bin '{b.name}'") for v in b.all_values()]
                for trb in cp.transitions:
                    checks += [
                        (v, f"transition '{trb.name}'") for v in trb.int_endpoints()
                    ]
                for v, where in checks:
                    if legal_enum is not None:
                        if v not in legal_enum:
                            raise ValueError(
                                f"coverage_model[{cm.agent}]: {where} on enum field "
                                f"'{cp.field}' has value {v}, which is not a declared "
                                f"enum label (the simulator would silently drop it)."
                            )
                    elif not (0 <= v <= hi):
                        raise ValueError(
                            f"coverage_model[{cm.agent}]: {where} on '{cp.field}' has "
                            f"value {v} outside 0..{hi} ({port.bit_width} bits)."
                        )
        seqs_by_agent = {a.name: {s.name for s in a.sequences} for a in self.agents}
        for t in self.tests:
            if t.sequence is None:
                continue
            sel = t.sequence
            if sel.agent not in agent_name_set:
                raise ValueError(
                    f"test '{t.name}': sequence selector references unknown agent "
                    f"'{sel.agent}'."
                )
            if sel.name not in seqs_by_agent[sel.agent]:
                raise ValueError(
                    f"test '{t.name}': sequence '{sel.name}' is not a declared "
                    f"sequence of agent '{sel.agent}' (add it to "
                    f"agents[{sel.agent}].sequences)."
                )
            sel_agent = next(a for a in self.agents if a.name == sel.agent)
            if not sel_agent.active:
                raise ValueError(
                    f"test '{t.name}': sequence selector targets passive agent "
                    f"'{sel.agent}' — a passive agent builds no sequencer to run on."
                )
            sel_seq = next(s for s in sel_agent.sequences if s.name == sel.name)
            if sel.count is not None and sel_seq.kind == "nested":
                raise ValueError(
                    f"test '{t.name}': sequence '{sel.name}' is a nested "
                    f"sequence-of-sequences and has no item count to override — set "
                    f"count on its steps instead."
                )
        # C2 — virtual sequences
        agents_by_name = {a.name: a for a in self.agents}
        vseq_names: set[str] = set()
        for vs in self.virtual_sequences:
            if vs.name in vseq_names:
                raise ValueError(
                    f"virtual_sequences: duplicate vsequence name '{vs.name}'."
                )
            vseq_names.add(vs.name)
            if vs.name == "env_vseq_base":
                raise ValueError(
                    "virtual_sequences: 'env_vseq_base' is a reserved name."
                )
            for step in vs.body:
                ag_obj = agents_by_name.get(step.agent)
                if ag_obj is None:
                    raise ValueError(
                        f"vsequence '{vs.name}': step references unknown agent "
                        f"'{step.agent}'."
                    )
                if not ag_obj.active:
                    raise ValueError(
                        f"vsequence '{vs.name}': step targets passive agent "
                        f"'{step.agent}' — no sequencer is built for it."
                    )
                valid_seqs = {s.name for s in ag_obj.sequences} | {f"{ag_obj.name}_seq"}
                if step.sequence not in valid_seqs:
                    raise ValueError(
                        f"vsequence '{vs.name}': step sequence '{step.sequence}' is "
                        f"not a library sequence of agent '{step.agent}' (nor its "
                        f"default '{ag_obj.name}_sequence')."
                    )
        # A test may name an explicit vsequence or the auto-default (<project>_vseq).
        valid_vseqs = vseq_names | ({self.auto_vseq_name} - {None})
        for t in self.tests:
            if t.vseq is not None and t.vseq not in valid_vseqs:
                raise ValueError(
                    f"test '{t.name}': vseq '{t.vseq}' is not a declared vsequence."
                )
        # K0 — the DPI-C reference model marshals each primary-agent field as a
        # scalar DPI arg (≤64-bit). Wider fields need svBitVecVal (a follow-up).
        if self.reference_model.language == "c":
            for _, p in self.agents[0].all_ports:
                if p.bit_width > 64:
                    raise ValueError(
                        f"reference_model.language='c': field '{p.name}' is "
                        f"{p.bit_width} bits; DPI-C scalar marshaling supports ≤64-bit "
                        f"fields (wider fields are not yet supported)."
                    )
        # All TB-owned typedefs — port enums (`<port>_e`), packed structs
        # (`<port>_<path>_t`) and struct enum members (`<port>_<path>_e`) — share the
        # tb_pkg scope. Names are paths joined by '_', so distinct paths can collide
        # (port 'a' member 'b_c' vs member 'b' → 'c', both 'a_b_c_t'; two enum ports
        # 'op' → 'op_e' x2; a port enum 'hdr_cls' vs a struct member 'hdr'.'cls', both
        # 'hdr_cls_e'). A duplicate emits two conflicting typedefs → a compile error,
        # so reject it at config time.
        seen_td: dict[str, str] = {}
        for a in self.agents:
            for _, p in a.all_ports:
                names = [p.sv_type] if p.enum else []  # <port>_e
                names += [td["name"] for td in p.struct_typedefs]
                where = f"{a.name}.{p.name}"
                for nm in names:
                    if nm in seen_td:
                        raise ValueError(
                            f"TB-owned typedef '{nm}' (from {where}) collides with the "
                            f"one from {seen_td[nm]} — enum/struct typedef names are "
                            f"derived from port + member names and must be unique "
                            f"across the bench. Rename a port or member."
                        )
                    seen_td[nm] = where
        return self

    def coverage_model_for(self, agent_name: str) -> CoverageModel | None:
        """The coverage model targeting `agent_name`, if any (V1)."""
        return next((c for c in self.coverage_models if c.agent == agent_name), None)

    @property
    def reg_bus_agent(self) -> AgentConfig | None:
        """The agent whose sequencer drives front-door register access."""
        if self.register_model is None:
            return None
        return next(
            (a for a in self.agents if a.name == self.register_model.bus_agent), None
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> ProjectConfig:
        with open(path) as fh:
            raw = yaml.safe_load(fh)
        return cls.model_validate(raw)

    @property
    def primary_agent(self) -> AgentConfig:
        """The first agent — used as default for scoreboard/coverage wiring."""
        return self.agents[0]

    @property
    def active_agents(self) -> list[AgentConfig]:
        """Agents with a sequencer to drive (active)."""
        return [a for a in self.agents if a.active]

    @property
    def auto_vseq_name(self) -> str | None:
        """Name of the auto-generated default virtual sequence, or None if none
        applies. Explicit `virtual_sequences` win; otherwise a default is
        synthesized for >=2 active agents when `auto_virtual_sequences` is on."""
        if self.virtual_sequences or not self.auto_virtual_sequences:
            return None
        if len(self.active_agents) < 2:
            return None
        return f"{self.dut.name}_vseq"

    @property
    def instance_views(self) -> list[InstanceView]:
        """C3 — the per-instantiation views (env/top/scoreboard) for agents that
        declare `instances`; empty when none do (the legacy per-agent wiring is
        used, byte-identical)."""
        views: list[InstanceView] = []
        for a in self.agents:
            for inst in a.instances:
                views.append(
                    InstanceView(a, inst.name, a.instance_param_args_values(inst))
                )
        return views

    @property
    def effective_virtual_sequences(self) -> list[VseqConfig]:
        """The virtual sequences the generator emits: the explicit ones, or the
        auto-default (one base sequence per active agent) for a multi-agent bench."""
        if self.virtual_sequences:
            return self.virtual_sequences
        name = self.auto_vseq_name
        if name is None:
            return []
        return [
            VseqConfig(
                name=name,
                mode=self.auto_vseq_mode,
                body=[
                    VseqStep(agent=a.name, sequence=f"{a.name}_seq")
                    for a in self.active_agents
                ],
            )
        ]
