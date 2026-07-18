"""Pydantic v2 data models for QuickUVM configuration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar, Literal, NamedTuple

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

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
    # --- Bidirectional (`inouts`) ports only ---------------------------------------
    # OPEN-DRAIN (I2C SDA/SCL, SMBus, any wired-AND bus): a driver may only pull the
    # line LOW or RELEASE it — it can never drive high. So driving a 1 IS releasing.
    # The generated interface emits
    #     assign <n> = (<n>_oe && !<n>_o) ? 1'b0 : 1'bz;
    # Requires width 1 (per-bit open-drain on a vector is a generate loop and nobody
    # has needed it); a plain tri-state bus (open_drain: false) drives both levels.
    open_drain: bool = False
    # A bus with no driver floats to X, which silently poisons every sample. A pullup
    # is what makes an open-drain line read as 1 when everyone has released it.
    pullup: bool = False
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


# "inouts" = an `inout` wire both the DUT and the TB drive (I2C SDA/SCL, any
# tri-state bus). It is a third category because neither TB-driven nor DUT-driven
# can express a net that must be RELEASED.
PortMap = dict[Literal["inputs", "outputs", "inouts"], list[PortConfig]]


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
    # I-9 — replicate this agent COUNT times into ONE DUT with vectored ports (N alert
    # lines, N interrupt channels): the alert_handler topology (one agent def, ~63x).
    # Distinct from C3 `instances` (different param values, each its own DUT): count
    # replicas are IDENTICAL and share one DUT, each bound to a slice of the vectors.
    # Opt-in; 1 (default) is the single-agent wiring, byte-identical.
    count: int = 1
    # Runtime: the agent's ORIGINAL name, captured before any H1 namespace prefix is
    # applied (like ProjectConfig.original_dut_name). So a cross-level endpoint into a
    # reused subtree can name the agent as originally declared (`g`, not `left_g`) and
    # the resolver maps it to the prefixed handle. "" = never prefixed.
    original_name: str = Field(default="", exclude=True, repr=False)
    # F2' — consume-by-reference. A referenced agent is wired into the env (its
    # <name>_pkg is imported and its classes instantiated) but its SOURCE is NOT
    # regenerated — it comes from an external, separately-generated VIP. The loader
    # (from_yaml) sets these from a VIP manifest when the bench declares `agent_refs:`;
    # a normally-declared agent has is_reference=False (byte-identical). `ref_filelist`
    # is the path to the VIP's <name>_pkg.f, chained with Cadence `-F` (relative to the
    # file), captured absolute at load and rewritten relative to the output dir on emit.
    is_reference: bool = Field(default=False, exclude=True, repr=False)
    ref_filelist: str = Field(default="", exclude=True, repr=False)
    # M1 — multi-clock/reset: name the clock domain / external reset this agent runs on.
    # None ⇒ the sole/first clock, and the reset bound to that clock (byte-identical for
    # a single-clock/single-reset bench).
    clock: str | None = None
    reset: str | None = None
    # M1 — multi AGENT-DRIVEN reset: name which of THIS agent's own input ports it
    # drives as reset (the driver parks it, sequences constrain it inactive, the monitor
    # samples it). None ⇒ fall back to the port named `dut.reset` if the agent has it
    # (single-reset bench is byte-identical). `reset_port_active_low` overrides the
    # `dut.reset_active_low` for this agent (None ⇒ global), for mixed-polarity multi-
    # agent resets. Distinct from `reset` (which names an EXTERNAL reset domain).
    reset_port: str | None = None
    reset_port_active_low: bool | None = None
    # K1 — emit an interface protocol checker (opt-in, byte-identical when False):
    # a sample SVA property on this agent's interface (an output is never X/Z once
    # reset deasserts) plus a `sva_properties` pragma region for your own protocol
    # assertions. Lives IN the interface (no bind), so it samples on the interface's
    # own clk/reset domain and is correct across multi-clock / C3 / H1 for free.
    assertions: bool = False

    # --- Reactive / responder (device) agent -------------------------------------
    # `responder`: the DUT initiates and this agent RESPONDS (an SPI device, a memory
    # slave, an I2C target). The port-direction model is UNCHANGED — the agent still
    # drives the DUT's inputs (which are now the RESPONSE) and samples the DUT's outputs
    # (which are now the REQUEST). Only the driver's timing and the sequence change.
    # Opt-in: `initiator` (default) is byte-identical.
    mode: Literal["initiator", "responder"] = "initiator"
    # Responder only: which SAMPLED port (a DUT output) means "a request arrived". The
    # monitor publishes the request on this qualifier.
    request_valid: str | None = None
    # Responder only, OPTIONAL — and its PRESENCE selects the driver shape:
    #
    #   absent  -> the BLOCKING responder (OpenTitan dv_reactive_agent / Verilab). The
    #              driver parks on get_next_item when it has no item. Correct when the
    #              slave's outputs are only meaningful during a transfer.
    #   present -> the CONTINUOUS responder (OpenHW OBI, CESNET OFM). The DUT samples
    #              our outputs (gnt/ready/valid) EVERY cycle, so parking leaves them
    #              stale or X. The driver becomes non-blocking (`try_next_item`) and
    #              drives these values on a miss, advancing a cycle either way.
    #
    # Declaring `idle:` IS the statement "this bus has a per-cycle obligation", and it
    # carries exactly what that shape needs. A separate `driver_style:` flag would be
    # redundant — and redundant knobs are how a schema starts lying.
    # Keys are DRIVEN ports (the agent's `inputs`).
    # See docs/reactive_agent_investigation.md.
    idle: dict[str, int] = Field(default_factory=dict)

    # HYBRID (initiator + responder). A responder that ALSO accepts proactive TB
    # stimulus on its sequencer — an alert-sender answers the DUT's pings AND
    # spontaneously raises alerts. Opt-in; only for `respond: on_request` (the shape
    # with a request FIFO + a blocking responder sequence). When true the agent STAYS a
    # responder — the env still forks its responder sequence — but it also joins the
    # stimulus agents, so the test starts a proactive sequence on the same sequencer and
    # UVM arbitrates the two (the responder sequence blocks on requests; the proactive
    # one drives when it has an item). Byte-identical when false.
    #
    # The subtlety this closes: the driver's DEAD_RESPONDER counts DRIVES, which the
    # proactive stimulus inflates — so a dead responder would be MASKED (it "drove
    # something", just never a response). A proactive responder therefore gets an
    # un-maskable request-drain liveness on its sequencer instead (proactive stimulus
    # never touches the request FIFO, so an unanswered request always shows).
    proactive: bool = False

    # F1 — THE RESPONSE-TIMING CONTRACT. Responder-only; opt-in; default = today's
    # shape.
    #
    # on_request (default): the DUT HOLDS its request until it is answered. The response
    #       lands the cycle AFTER the request is sampled — STRUCTURALLY, because it
    #       round-trips monitor -> analysis fifo -> responder sequence -> sequencer ->
    # driver -> cb1. That round-trip costs at least one cycle and no pragma can run
    # inside it. `memslave` is correct under this contract only because its FSM sits
    #       in REQ forever, waiting.
    # combinational: ZERO SLACK. The DUT samples our response on the very next edge, so
    # there is no time for a sequencer round-trip. The response is therefore a pure
    #       FUNCTION, evaluated in the driver on the RAW request signals — no clocking
    #       block (cb1's output skew lands after the edge the DUT samples on), no
    #       sequencer, no request fifo. It MAY depend on the current request.
    #
    # A serial device (SPI, full-duplex) needs a THIRD contract — prefetch, where the
    # item
    # is in the driver's hands before the transfer starts, because MISO bit k cannot
    # depend
    # on MOSI bit k. That needs a clock the TB does not generate, so it lands with the
    # sampled clock, where a bench can actually prove it.
    respond: Literal["on_request", "prefetch", "combinational", "pipelined"] = (
        "on_request"
    )

    # PIPELINED responder only. Names the SAMPLED request field (an `outputs` port, e.g.
    # AXI's `arid`) that identifies a transaction. Requests are bucketed into per-ID
    # queues: same-ID answered in arrival order (the AXI ordering rule), cross-ID free
    # to reorder. Without it there is no notion of "which outstanding request is this",
    # so a pipelined responder cannot answer out of order — hence it is required for,
    # and only for, `respond: pipelined`.
    reorder_by: str | None = None

    # PIPELINED responder only. The CROSS-ID arbitration when more than one id has a
    # request waiting (same-ID is always arrival order). `priority` = lowest ready id
    # first (deterministic, the default — can starve a high id under sustained load);
    # `round_robin` = the next ready id after the one served last, wrapping (fair, no
    # starvation); `random` = any ready id (matches PULP's axi_rand_slave). Same-ID FIFO
    # order and the no-strand guarantee hold under every policy.
    reorder_policy: Literal["priority", "round_robin", "random"] = "priority"

    @property
    def is_responder(self) -> bool:
        return self.mode == "responder"

    @property
    def has_responder_seq(self) -> bool:
        """Whether a forever responder SEQUENCE feeds the driver.

        `on_request` and `prefetch` both need one — the driver takes its items from a
        sequencer. They differ in WHEN: on_request's sequence blocks on the observed
        request; prefetch's runs ahead of it, so the driver always has an item in hand.
        A zero-slack responder has no sequencer at all: its driver IS the responder.
        """
        return self.is_responder and not self.is_zero_slack

    @property
    def is_prefetch(self) -> bool:
        """The item must be in the driver's hands BEFORE the transfer starts."""
        return self.is_responder and self.respond == "prefetch"

    @property
    def is_zero_slack(self) -> bool:
        """The DUT gives us ONE cycle. No sequencer round-trip is fast enough."""
        return self.is_responder and self.respond == "combinational"

    @property
    def is_pipelined(self) -> bool:
        """MULTI-OUTSTANDING, out-of-order responder (AXI-style).

        The `on_request` sequence answers ONE response per incoming request (get ->
        respond -> get), so a burst that arrives faster than it is answered is stranded:
        after draining the backlog into a buffer it blocks on a NEW request that never
        comes. A pipelined responder decouples accept from drive — one thread buffers
        every request into per-ID queues, a second drains those queues without waiting
        on the bus — so N requests can be outstanding and answered out of order by
        `reorder_by`. See docs/t6_axi_outstanding_assessment.md.
        """
        return self.is_responder and self.respond == "pipelined"

    @property
    def has_request_fifo(self) -> bool:
        """Whether the response path runs through the monitor -> fifo -> sequence chain.

        A zero-slack responder cannot: that chain costs a cycle it does not have. Its
        driver reads the raw request signals itself. The pipelined shape needs it too —
        its accept thread drains exactly this fifo into per-ID queues.
        """
        return self.is_responder and self.respond in ("on_request", "pipelined")

    @property
    def is_continuous(self) -> bool:
        """The CONTINUOUS responder shape — non-blocking driver + drive-idle-on-miss."""
        return self.is_responder and bool(self.idle) and self.respond == "on_request"

    @property
    def is_proactive(self) -> bool:
        """HYBRID responder: answers the DUT AND accepts proactive TB stimulus on its
        sequencer. Only for on_request — its request FIFO's drain is the un-maskable
        liveness (DEAD_RESPONDER's drive count is inflated by proactive stimulus)."""
        return self.is_responder and self.proactive

    @property
    def responder_seq_name(self) -> str:
        """The forever responder sequence (`<agent>_responder_seq`)."""
        return f"{self.name}_responder_seq"

    @property
    def default_seq_name(self) -> str:
        """Class name / file stem of the generated default per-agent sequence
        (`<agent>_seq`). Centralized here so the duplicate-name collision check, the
        vseq step valid-set, the auto-vseq wiring, the generator FileSpec, and the
        sequence + test templates all derive it from one place."""
        return f"{self.name}_seq"

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
    def inout_ports(self) -> list[PortConfig]:
        """BIDIRECTIONAL (`inout`) ports — a shared wire both the DUT and the TB drive.

        Neither `inputs` (TB-driven) nor `outputs` (DUT-driven) can express this: the
        net is a `wire`, resolved from both sides, and the TB must be able to RELEASE
        it. Each inout port yields three transaction fields: `<n>_o` (what we drive),
        `<n>_oe` (whether we drive at all) and `<n>` (the RESOLVED value sampled back).
        """
        return self.ports.get("inouts", [])

    @property
    def has_inouts(self) -> bool:
        return bool(self.inout_ports)

    @property
    def driven_fields(self) -> dict[str, PortConfig]:
        """Every transaction field this agent DRIVES at the DUT, by name.

        The `inputs`, plus the two fields each `inouts` port synthesises: `<n>_o` (the
        value) and `<n>_oe` (whether we drive it at all). A SERIAL DEVICE drives ONLY
        inouts — an SPI device owns nothing but the shared `sd` lines — so a responder
        whose driven set ignored them would have "nothing to drive as a response" and be
        rejected outright. `<n>_oe` is per-LANE (it has the port's width), because the
        host may own sd[0] while the device owns sd[1] at the same instant.
        """
        out: dict[str, PortConfig] = {p.name: p for p in self.input_ports}
        for p in self.inout_ports:
            out[f"{p.name}_o"] = p.model_copy(update={"name": f"{p.name}_o"})
            out[f"{p.name}_oe"] = p.model_copy(update={"name": f"{p.name}_oe"})
        return out

    @property
    def coverable_fields(self) -> dict[str, PortConfig]:
        """Every transaction field a coverpoint/scoreboard may name.

        That is the declared ports PLUS the fields an `inouts` port synthesises:
        `<n>_o` (what we drive) and `<n>_oe` (whether we drive). `<n>_oe` is usually
        the most interesting thing on a shared bus (who is holding the line?), so
        refusing to cover it would make the feature half-useless.
        """
        out: dict[str, PortConfig] = {p.name: p for _, p in self.all_ports}
        out.update(self.driven_fields)
        return out

    @property
    def all_ports(self) -> list[tuple[Literal["input", "output", "inout"], PortConfig]]:
        """Every DUT port this agent touches, tagged with its DIRECTION AT THE DUT.

        `inout` ports come last and are emitted as `inout wire` on the DUT — a shared
        net, not a driven one.
        """
        result: list[tuple[Literal["input", "output", "inout"], PortConfig]] = []
        for p in self.output_ports:
            result.append(("output", p))
        for p in self.input_ports:
            result.append(("input", p))
        for p in self.inout_ports:
            result.append(("inout", p))
        return result

    @field_validator("name", "interface", "sequence_item")
    @classmethod
    def no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError(f"Name '{v}' must not contain spaces.")
        return v

    @model_validator(mode="after")
    def _check_inouts(self) -> AgentConfig:
        """Fail-closed rules for bidirectional (`inout`) ports."""
        uni = {p.name for p in self.input_ports} | {p.name for p in self.output_ports}
        for p in self.inout_ports:
            if p.name in uni:
                raise ValueError(
                    f"agent '{self.name}': inout port '{p.name}' also appears in "
                    f"inputs/outputs. A net is driven from one side or both — pick one."
                )
            if p.open_drain and p.bit_width != 1:
                raise ValueError(
                    f"agent '{self.name}': open_drain port '{p.name}' must be 1 bit "
                    f"(got {p.bit_width}). Per-bit open-drain on a vector needs a "
                    f"generate loop; declare one port per line."
                )
            if p.open_drain and not p.pullup:
                raise ValueError(
                    f"agent '{self.name}': open-drain port '{p.name}' needs "
                    f"`pullup: true`. An open-drain line is never driven high; with "
                    f"no pullup it floats to X the moment everyone releases, and every "
                    f"sample downstream is poisoned. Not a style preference."
                )
        # The transaction adds `<n>_o` / `<n>_oe` per inout port; they must not
        # collide with a declared port of the same name.
        for p in self.inout_ports:
            for suffix in ("_o", "_oe"):
                gen = f"{p.name}{suffix}"
                if gen in uni or any(b.name == gen for b in self.inout_ports):
                    raise ValueError(
                        f"agent '{self.name}': inout port '{p.name}' generates the "
                        f"transaction field '{gen}', which collides with a declared "
                        f"port. Rename one."
                    )
        return self

    @model_validator(mode="after")
    def _check_responder(self) -> AgentConfig:
        """Fail-closed rules for the reactive/responder agent.

        NB the port-direction model is UNCHANGED: a responder still DRIVES the DUT's
        `inputs` (its response) and SAMPLES the DUT's `outputs` (the DUT's request). So
        `request_valid` names a SAMPLED port and `idle` keys name DRIVEN ports.
        """
        driven = self.driven_fields
        sampled = {p.name: p for p in self.output_ports}

        if not self.is_responder:
            if self.request_valid is not None:
                raise ValueError(
                    f"agent '{self.name}': `request_valid` is only valid with "
                    f"`mode: responder` (an initiator has no DUT request to wait for)."
                )
            if self.idle:
                raise ValueError(
                    f"agent '{self.name}': `idle` is only valid with `mode: responder` "
                    f"(it selects the continuous, non-blocking responder driver)."
                )
            if self.reorder_by is not None:
                raise ValueError(
                    f"agent '{self.name}': `reorder_by` is only valid with "
                    f"`mode: responder` + `respond: pipelined`."
                )
            if self.reorder_policy != "priority":
                raise ValueError(
                    f"agent '{self.name}': `reorder_policy` is only valid with "
                    f"`mode: responder` + `respond: pipelined`."
                )
            if self.proactive:
                raise ValueError(
                    f"agent '{self.name}': `proactive` is only valid with "
                    f"`mode: responder` (it makes a responder ALSO accept TB stimulus)."
                )
            return self

        if not self.active:
            raise ValueError(
                f"agent '{self.name}': `mode: responder` requires `active: true`. A "
                f"responder DRIVES its response — reactive and passive are orthogonal "
                f"(a reactive slave is an ACTIVE component)."
            )
        if not driven:
            raise ValueError(
                f"agent '{self.name}': `mode: responder` needs an `inputs` or `inouts` "
                f"port — there is nothing to drive as a response."
            )
        if self.instances:
            raise ValueError(
                f"agent '{self.name}': `mode: responder` is not yet supported with C3 "
                f"`instances` — each instance would need its own responder, and the "
                f"generated test starts per-instance stimulus on every instance's "
                f"sequencer (which a responder's forever sequence owns)."
            )
        if self.proactive and self.respond != "on_request":
            raise ValueError(
                f"agent '{self.name}': `proactive` requires `respond: on_request` — a "
                f"hybrid's un-maskable liveness is the request-FIFO drain, which only "
                f"on_request has (prefetch/combinational have no request FIFO; "
                f"pipelined already carries its own STRANDED_REQUESTS check)."
            )
        if self.proactive and self.idle:
            raise ValueError(
                f"agent '{self.name}': `proactive` is incompatible with `idle` — a "
                f"continuous (non-blocking) responder drives every cycle, leaving no "
                f"room for a proactive sequence to interleave. A hybrid uses the "
                f"BLOCKING on_request driver (its responder sequence parks on the "
                f"request FIFO, so a proactive sequence gets the sequencer when idle)."
            )
        if self.request_valid is None:
            raise ValueError(
                f"agent '{self.name}': `mode: responder` requires `request_valid`: the "
                f"sampled port that means 'the DUT issued a request'."
            )
        rv = sampled.get(self.request_valid)
        if rv is None:
            raise ValueError(
                f"agent '{self.name}': request_valid='{self.request_valid}' must name "
                f"one of this agent's SAMPLED ports (its `outputs` — the DUT drives "
                f"the request). Sampled ports: {sorted(sampled)}."
            )
        if rv.bit_width != 1:
            raise ValueError(
                f"agent '{self.name}': request_valid='{self.request_valid}' must be "
                f"1 bit (it is a qualifier), got {rv.bit_width}."
            )
        for name, val in self.idle.items():
            p = driven.get(name)
            if p is None:
                raise ValueError(
                    f"agent '{self.name}': idle port '{name}' must be one of this "
                    f"agent's DRIVEN ports (its `inputs` — what it drives at the DUT). "
                    f"Driven ports: {sorted(driven)}."
                )
            if not 0 <= val < (1 << p.bit_width):
                raise ValueError(
                    f"agent '{self.name}': idle value {val} for port '{name}' does not "
                    f"fit its {p.bit_width}-bit width."
                )

        # PIPELINED — reorder_by names the sampled ID field the per-queue buckets use.
        if self.is_pipelined:
            if self.reorder_by is None:
                raise ValueError(
                    f"agent '{self.name}': `respond: pipelined` requires `reorder_by`: "
                    f"the sampled request field (an `outputs` port, e.g. AXI's `arid`) "
                    f"that identifies which outstanding transaction a response answers "
                    f"— without it there is no per-ID ordering, no way to reorder."
                )
            rb = sampled.get(self.reorder_by)
            if rb is None:
                raise ValueError(
                    f"agent '{self.name}': reorder_by='{self.reorder_by}' must name a "
                    f"SAMPLED port (`outputs`, DUT-driven). Sampled ports: "
                    f"{sorted(sampled)}."
                )
            if self.reorder_by == self.request_valid:
                raise ValueError(
                    f"agent '{self.name}': reorder_by cannot be the request_valid "
                    f"qualifier '{self.request_valid}' — it must be the ID field that "
                    f"distinguishes outstanding requests, not the valid strobe."
                )
            # The generated pick keys buckets with `id_q[int'(<id>)]` and (round_robin)
            # seeds the cursor at -1. A field >= 32 bits could cast to a negative int
            # and alias that sentinel / a real id, so cap the width — a transaction-id
            # space that large is not a real design anyway.
            if rb.bit_width > 31:
                raise ValueError(
                    f"agent '{self.name}': reorder_by='{self.reorder_by}' is "
                    f"{rb.bit_width} bits — too wide for the per-ID pick (keep it "
                    f"<= 31; an id space that large is not a real transaction id)."
                )
        elif self.reorder_by is not None:
            raise ValueError(
                f"agent '{self.name}': `reorder_by` is only valid with "
                f"`respond: pipelined` (got respond='{self.respond}')."
            )
        if not self.is_pipelined and self.reorder_policy != "priority":
            raise ValueError(
                f"agent '{self.name}': `reorder_policy` is only valid with "
                f"`respond: pipelined` (got respond='{self.respond}')."
            )
        return self

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
            if s.name == self.default_seq_name:
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
        # I-9 — count: N identical replicas sharing one vectored DUT.
        if self.count < 1:
            raise ValueError(f"agent '{self.name}': `count` must be >= 1.")
        if self.count > 1:
            if self.instances or self.parameters:
                raise ValueError(
                    f"agent '{self.name}': `count` (identical replicas into one "
                    f"vectored DUT) is mutually exclusive with C3 `instances`/"
                    f"`parameters` (those give each instance its own DUT at a width)."
                )
            if self.is_responder:
                raise ValueError(
                    f"agent '{self.name}': `count` is not yet supported with "
                    f"`mode: responder` — the shared-DUT replica wiring is validated "
                    f"for initiator agents (N stimulus/monitor channels into one DUT)."
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

    def __init__(
        self,
        agent: AgentConfig,
        name: str,
        pav: str,
        shared: bool = False,
        index: int = 0,
    ):
        self.agent = agent
        self.name = name  # instance base name, e.g. io8
        self.pav = pav  # concrete args for this instance, e.g. #(16)
        # I-9 — a `count` replica: all replicas share ONE vectored DUT (this instance
        # binds to bit `index` of each port). C3 `instances` leave these default.
        self.shared = shared
        self.index = index

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


# M1 mixed-unit — SI time-unit magnitudes relative to fs, for resolving a single
# `-timescale` (the finest/smallest unit across the clocks) and scaling each clock's
# period into it (Xcelium takes one -timescale for the whole elaboration).
_UNIT_MAG = {
    "fs": 1,
    "ps": 1_000,
    "ns": 1_000_000,
    "us": 1_000_000_000,
    "ms": 1_000_000_000_000,
    "s": 1_000_000_000_000_000,
}


class ClockConfig(BaseModel):
    # M1 — multi-clock: `name` is the clock NET name in tb_top (and the DUT's clock
    # port). Default "clk" so a single-clock bench is byte-identical. `clock:` in the
    # YAML accepts one ClockConfig (today) or a LIST of them (a domain each).
    name: str = "clk"
    period: int = 10
    unit: str = "ns"
    drive_offset_pct: int = 20  # percent of period to delay drive after posedge

    # F2 — WHO DRIVES THIS CLOCK.
    #
    #   tb  (default): the TB generates it. A `clkgen` in tb_top drives the net.
    #   dut: the DUT OUTPUTS it and the TB only ever SAMPLES it — an SPI `sck`, an I2C
    #        `scl`. NO clkgen is emitted: one would fight the DUT's output driver and
    #        Xcelium rejects it (*E,MULDRN). `period` is then never used to make an
    # edge;
    #        it is only a hint for timeouts.
    #
    # This is not a cosmetic distinction. Get it wrong in the `dut` direction and the
    # bench
    # is keyed to a TB-invented PHANTOM CLOCK unrelated to the DUT's real one — it
    # runs, it
    # passes, and it measures nothing. `_check_observed_clock_is_connected` in the
    # generator
    # makes that unreachable rather than merely documented.
    source: Literal["tb", "dut"] = "tb"

    @property
    def observed(self) -> bool:
        """The DUT drives this clock; the TB samples it and must never drive it."""
        return self.source == "dut"

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        _check_sv_identifier(v, "clock name")
        return v


class DrivenReset(NamedTuple):
    """M1 — an agent-driven reset (the agent's sequences drive it): the reset PORT name
    + its active-low polarity. Returned by `ProjectConfig.agent_driven_reset`."""

    name: str
    active_low: bool


class ResetConfig(BaseModel):
    """M1 — one externally-generated reset domain. `clock` names the ClockConfig whose
    posedge the deassert synchronizes to (sync reset); None ⇒ asynchronous (deassert
    after a fixed delay). A single-reset bench is synthesized from `dut.reset` /
    `reset_active_low` / `external_reset` when `resets` is empty (byte-identical)."""

    name: str
    active_low: bool = True
    clock: str | None = None  # bound clock domain (sync deassert); None ⇒ async

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        _check_sv_identifier(v, "reset name")
        return v


class TestConfig(BaseModel):
    name: str
    num_items: int = 100
    # S2 — run a selected agent-library sequence instead of the default
    # <primary>_sequence. None ⇒ today's behavior (byte-identical).
    sequence: TestSeqSel | None = None
    # C2 — run a virtual sequence on the env's vsqr (coordinates >=2 agents).
    vseq: str | None = None
    # R1 — how many seeds `make regress` runs this test at. None ⇒ regress.seeds.
    # Only read when a `regress:` block is present; renders nothing otherwise.
    seeds: int | None = None

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
        if self.seeds is not None and self.seeds < 1:
            raise ValueError(
                f"test '{self.name}': seeds must be >= 1 (got {self.seeds})."
            )
        return self


class WindowSpec(BaseModel):
    """A WINDOWED scoreboard (opt-in). A health-test / statistics block accumulates N
    raw samples and emits ONE verdict per window (an N:1 statistic), keyed off a DUT
    boundary strobe. The generated predictor carries the sample counter, the boundary
    keying, the copy-through cadence, and — crucially — the DUAL window-length liveness:
    a boundary at the wrong sample count AND a window that never closes both fail, so
    the strobe the verdict keys off is not a guard trusting itself. The user fills only
    the domain accumulate + verdict in the window_accumulate / window_verdict seams.

    Single-stream only (predict feeds both the predictor and the comparator's actual, so
    the boundary override folds the N:1 statistic into the 1:1 cadence); a two-stream
    scoreboard is strictly 1:1 and would desync N samples against 1 verdict. See
    examples/es_adaptp and docs/es_adaptp_assessment.md.
    """

    # A source-agent OUTPUT port: the DUT strobe that closes a window (predict()
    # overrides the verdict on the cycle this field is set).
    boundary: str
    # Samples per window — the length the liveness holds each window to.
    length: int

    @model_validator(mode="after")
    def _check(self) -> WindowSpec:
        _check_sv_identifier(self.boundary, "window boundary signal")
        if self.length < 1:
            raise ValueError("scoreboard window length must be >= 1 sample.")
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
    # Windowed scoreboard (opt-in, single-stream only). None => the plain predictor
    # (byte-identical when unused).
    window: WindowSpec | None = None

    @model_validator(mode="after")
    def _check_match(self) -> ScoreboardSpec:
        # The name appears in generated class names (<dut>_<name>_predictor, ...) when
        # there are >=2 scoreboards, so it must be a legal SV identifier.
        _check_sv_identifier(self.name, "scoreboard name")
        if self.window is not None and self.monitor is not None:
            raise ValueError(
                f"scoreboard '{self.name}': window requires a SINGLE-stream scoreboard "
                f"(omit 'monitor'). A two-stream scoreboard is strictly 1:1 and cannot "
                f"fold N samples into one per-window verdict."
            )
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

    `language: sv` (default) keeps the `predict()` body in
    `<dut>_reference_model.svh`. `language: c` also generates a DPI-C **bridge**: an
    SV marshaling layer + a `<dut>_reference_model.c` stub whose signature is derived
    from the primary agent's fields.

    WHAT `language: c` IS FOR -- and what it is not.
    The bridge models a golden model as a **pure scalar function**: scalars in, scalar
    pointers out, <=64 bits each, one call per transaction. That fits a small
    combinational model (see `examples/sat_adder/`).

    It does NOT fit a real golden model, because real golden models are LIBRARIES:
    OpenTitan `cryptoc` takes open-array byte streams and returns an 8-word digest;
    Spike is a `chandle` you STEP; Caliptra's predictor shells out to Python. None of
    those is a pure scalar function -- and none of them needs the bridge.

    The seam already has the escape hatch: keep `language: sv`, declare the library's
    own `import "DPI-C"` (via `project.imports` or the tb_pkg `imports` pragma), and
    call it from the `prediction_logic` pragma. The predictor is a CLASS, so it can
    hold state across transactions -- accumulate a stream, trigger on a control event,
    serve a result back later. `examples/hmac/` does exactly that.

    See docs/reference_model_seam.md.
    """

    language: Literal["sv", "c"] = "sv"


class ProjectMeta(BaseModel):
    name: str
    author: str = ""
    year: int = 2026
    uvm_version: Literal["1.1d", "1.2"] = "1.2"  # selects version-specific UVM APIs
    # F2' — VIP identity. Stamped into a generated VIP's manifest (.qvip) so a
    # consuming bench records which VERSION of the VIP it wired in by reference.
    # Pure metadata; changes nothing for a bench that never generates/consumes a VIP.
    version: str = "0.1.0"
    # Packages to import into tb_pkg (e.g. for PortConfig.type external references).
    # Prefer the black-box default (generated enums); use this only when the TB
    # genuinely must share a spec/DUT package.
    imports: list[str] = Field(default_factory=list)


class SubenvConfig(BaseModel):
    """H1 — one child block environment composed into a subsystem (top) bench.

    `config` is the path to the child block's own QuickUVM config (resolved
    relative to the top config file). The child's reusable env layer (its
    packaged `<block>_env_pkg` + agent VIPs) is generated alongside the top, and
    the top env instantiates it. Opt-in: a bench with no `subenvs` is unchanged.
    """

    name: str  # instance name of the block in the top env (e.g. adder)
    config: str  # path to the child block config, relative to the top config
    # H1 param propagation — override the child block's agent parameter defaults
    # for this instance (e.g. {W: 16}). The value is baked into the block's env
    # (its VIP/scoreboard/DUT are generated at that width). Empty → block defaults.
    # NB: the block DUT is instantiated with POSITIONAL args in the agent's
    # parameter order (as in C3), so a multi-parameter block's agent `parameters:`
    # order must match the DUT module's parameter order.
    params: dict[str, int] = Field(default_factory=dict)
    # H1 reuse — per-instance class namespacing. Simple by default, powerful when
    # needed: None (default) auto-namespaces this instance (prefix = subenv name)
    # ONLY when the same `config` path is composed >=2 times (so the reused block's
    # classes don't collide); a config used once stays unprefixed (byte-identical).
    # `true` forces namespacing by the subenv name; a string forces a custom prefix;
    # `false` disables it (a genuine collision then fails closed).
    namespace: bool | str | None = None

    def resolve_prefix(self, is_shared: bool) -> str:
        """The class-name prefix for this instance ("" = no namespacing)."""
        ns = self.namespace
        if ns is False:
            return ""
        if ns is True:
            return self.name
        if isinstance(ns, str):
            return ns
        return self.name if is_shared else ""  # None → auto

    @model_validator(mode="after")
    def _check(self) -> SubenvConfig:
        _check_sv_identifier(self.name, "subenv name")
        if isinstance(self.namespace, str):
            _check_sv_identifier(self.namespace, "subenv namespace prefix")
        return self


class SubenvConnection(BaseModel):
    """H1 — a wire between two composed blocks: the source block's output port
    drives the destination block's input port (a pipeline). Each endpoint is a
    dotted path `<block>.<port>`, or `<sub>...<block>.<port>` to reach a LEAF block
    inside a nested subsystem (cross-level). The path is relative to the level that
    declares the connection; the last segment is the interface port. The
    destination block's agent must be passive (the connection, not the agent,
    drives it)."""

    model_config = ConfigDict(populate_by_name=True)
    src: str = Field(alias="from")  # <block>.<port>, or <sub>...<block>.<port>
    dst: str = Field(alias="to")  # <block>.<port>, or <sub>...<block>.<port>


class SubenvScoreboard(BaseModel):
    """H1 — a cross-block scoreboard: predict the monitor block's output from the
    source block's transaction and compare (reusing the A2 two-stream, in-order
    comparator). Each of `source`/`monitor` is a dotted path `<block>.<agent>`, or
    `<sub>...<block>.<agent>` to reach a LEAF block inside a nested subsystem
    (cross-level); the path is relative to the declaring level, last segment the
    agent."""

    name: str
    source: str  # <block>.<agent> — the stimulus/source stream
    monitor: str  # <block>.<agent> — the response/actual stream

    @model_validator(mode="after")
    def _check(self) -> SubenvScoreboard:
        _check_sv_identifier(self.name, "cross-block scoreboard name")
        if self.source == self.monitor:
            raise ValueError(
                f"cross-block scoreboard '{self.name}': source and monitor must "
                f"differ (a cross-block scoreboard spans two blocks)."
            )
        return self


class SubenvView:
    """A composed child block env, for the top composition templates. Not user
    config — built by `ProjectConfig.subenv_views` from the loaded child config."""

    def __init__(self, name: str, cfg: ProjectConfig, prefix: str = ""):
        self.name = name  # block instance name in the top (e.g. adder)
        self.cfg = (
            cfg  # the child's ProjectConfig (names already prefixed if namespaced)
        )
        self.prefix = prefix  # applied namespace prefix ("" = not namespaced)

    @property
    def namespaced(self) -> bool:
        return bool(self.prefix)

    @property
    def block(self) -> str:
        return self.cfg.dut.name  # child class prefix (e.g. adder / lo_chan)

    @property
    def dut_module(self) -> str:
        """The DUT module name to instantiate (real RTL). For a namespaced block
        this is the ORIGINAL block name (the reused RTL module is unprefixed),
        captured before any prefix was applied — robust to stacked prefixes."""
        return self.cfg.original_dut_name or self.cfg.dut.name

    @property
    def env_class(self) -> str:
        return f"{self.cfg.dut.name}_env"

    @property
    def env_cfg_class(self) -> str:
        return f"{self.cfg.dut.name}_env_cfg"

    @property
    def env_pkg(self) -> str:
        return f"{self.cfg.dut.name}_env_pkg"

    @property
    def is_subsystem(self) -> bool:
        """H1 nested — this child is itself a subsystem (composes its own blocks)."""
        return bool(self.cfg.subenvs)

    @property
    def vsqr_type(self) -> str:
        return f"{self.cfg.dut.name}_virtual_sequencer"

    @property
    def vseq_type(self) -> str:
        return f"{self.cfg.dut.name}_vseq"

    @property
    def inst(self) -> str:
        # The child env handle / component name in the top env. Kept as the plain
        # subenv name so it never collides with the child env CLASS (<block>_env)
        # when the subenv is named after its block (the natural choice).
        return self.name

    @property
    def cfg_field(self) -> str:
        return f"{self.name}_cfg"  # child env_cfg handle in the top env_cfg

    @property
    def agents(self) -> list[AgentConfig]:
        return self.cfg.agents

    @property
    def dut_param_args(self) -> str:
        """The block DUT's concrete `#(W)` args (H1 param propagation). A
        parameterized block is single-agent, so it is the (sole) agent's values,
        emitted POSITIONALLY in the agent's parameter order — the DUT module's
        parameter order must match (as in C3). Empty for a non-parameterized block."""
        return self.cfg.agents[0].param_args_values if self.cfg.agents else ""

    @property
    def dut_conns(self) -> list[tuple[str, str]]:
        """(interface-instance, port) pairs for wiring this block's DUT in the
        top tb_top — flattened across the block's agents."""
        out: list[tuple[str, str]] = []
        for a in self.cfg.agents:
            inst = f"{self.name}_{a.interface}_inst"
            for _, p in a.all_ports:
                out.append((inst, p.name))
        return out


class LeafView:
    """H1 nested — a flattened leaf block (a subenv with no subenvs of its own),
    carrying the path of subenv names from the top. Used by tb_top to instantiate
    every leaf's interfaces + DUT with tree-unique, path-prefixed names. At depth 1
    (a flat subsystem) `pathname == subenv name`, so names are byte-identical."""

    def __init__(self, sv: SubenvView, path: list[str]):
        self.sv = sv
        self.path = path

    @property
    def pathname(self) -> str:
        return "_".join(self.path)

    @property
    def agents(self) -> list[AgentConfig]:
        return self.sv.agents

    @property
    def dut_module(self) -> str:
        return self.sv.dut_module

    @property
    def dut_param_args(self) -> str:
        return self.sv.dut_param_args

    @property
    def dut_conns(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for a in self.sv.cfg.agents:
            inst = f"{self.pathname}_{a.interface}_inst"
            for _, p in a.all_ports:
                out.append((inst, p.name))
        return out

    # ---- M1 clocked-subenv — per-leaf clock/reset domain (empty for a combinational
    # leaf, which keeps the shared cadence `clk`). Nets are pathname-prefixed so two
    # clocked leaves that both default `clk`/`rst_n` never collide in the flat tb_top.

    @property
    def clocked(self) -> bool:
        return not self.sv.cfg.dut.combinational

    @property
    def clock_net(self) -> str:
        """This clocked leaf's tb_top clock NET (e.g. `acc_clk`)."""
        return f"{self.pathname}_{self.sv.cfg.effective_clocks[0].name}"

    @property
    def clock_port(self) -> str:
        """The leaf DUT's clock PORT name (unprefixed — a module port)."""
        return self.sv.cfg.dut.clock

    @property
    def clock_period_ts(self) -> int:
        return self.sv.cfg.clock_period_ts(self.sv.cfg.effective_clocks[0])

    @property
    def reset(self) -> ResetConfig | None:
        er = self.sv.cfg.effective_resets
        return er[0] if er else None

    @property
    def reset_net(self) -> str:
        r = self.reset
        return f"{self.pathname}_{r.name}" if r else ""

    @property
    def reset_port(self) -> str:
        """The leaf DUT's / interface's reset PORT name (unprefixed)."""
        return self.sv.cfg.dut.reset


def _apply_namespace_prefix(cfg: ProjectConfig, prefix: str) -> None:
    """H1 nested reuse — recursively prefix a composed subtree's class names by
    `prefix` (stacking on any inner prefix), so the SAME subsystem config reused
    twice yields collision-free class sets. `original_dut_name` / `original_name` are
    captured once (idempotent) so `SubenvView.dut_module` recovers the true RTL module
    name and a cross-level endpoint can name a reused leaf agent as originally declared,
    regardless of how many prefixes stack."""
    if not cfg.original_dut_name:
        cfg.original_dut_name = cfg.dut.name
    cfg.dut.name = f"{prefix}_{cfg.dut.name}"
    for a in cfg.agents:
        if not a.original_name:
            a.original_name = a.name
        a.name = f"{prefix}_{a.name}"
        a.interface = f"{prefix}_{a.interface}"
        a.sequence_item = f"{prefix}_{a.sequence_item}"
        for seq in a.sequences:
            seq.name = f"{prefix}_{seq.name}"
    for name, gc in cfg.subenv_configs.items():
        _apply_namespace_prefix(gc, prefix)
        old = cfg.subenv_namespaces.get(name, "")
        cfg.subenv_namespaces[name] = f"{prefix}_{old}" if old else prefix


def _all_descendant_agents(cfg: ProjectConfig) -> list[AgentConfig]:
    """Every agent in the composed subtree (all depths)."""
    out = list(cfg.agents)
    for gc in cfg.subenv_configs.values():
        out.extend(_all_descendant_agents(gc))
    return out


def _bake_param(cfg: ProjectConfig, name: str, value: int) -> None:
    """H1 nested param propagation — set parameter `name`'s default to `value` on
    every descendant agent that declares it (broadcast down the subtree)."""
    for a in cfg.agents:
        for p in a.parameters:
            if p.name == name:
                p.default = value
    for gc in cfg.subenv_configs.values():
        _bake_param(gc, name, value)


def _leaf_agent(cfg: ProjectConfig, token: str) -> AgentConfig | None:
    """The leaf agent a cross-level endpoint's trailing token names, or None. Under H1
    reuse an agent's name is prefixed (`g` → `left_g`); the endpoint uses the ORIGINAL
    name, so match on `original_name` (falling back to `name` when not reused). The
    returned agent's `.name` is the (possibly prefixed) handle the templates emit."""
    return next((a for a in cfg.agents if (a.original_name or a.name) == token), None)


class ProbeConfig(BaseModel):
    """K2 — a whitebox PROBE: passively OBSERVE (never drive) one INTERNAL DUT signal
    via a hierarchical reference (XMR), republished on a generated probe interface for
    coverage / checkers / debug.

    `path` is a plain hierarchical string RELATIVE to the DUT instance (e.g.
    `u_core.u_fifo.fill_level`); the generator prepends the DUT instance path, so an
    external tool that knows each net's full path can emit probes directly. The observed
    FIELD reuses the PortConfig type machinery (width / enum / type / packed_dims /
    struct), so an observed enum FSM gets SYMBOLIC coverage; `real` observes a real
    signal (SVA-checkable, but NOT covergroup-legal — SV forbids a real coverpoint).

    Observe-only by construction: the generated code READS the signal (a continuous
    `assign` into an interface INPUT) — it never `force`/`deposit`s. Driving internals
    stays out of scope (it would make the TB, not the DUT, the source of truth)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    width: int = 1
    enum: dict[str, int] | None = None
    type: str | None = None
    packed_dims: list[int] | None = None
    struct: list[StructMember] | None = None
    real: bool = False
    # M1 — the clock domain this probe is sampled on (None ⇒ the sole/first clock).
    clock: str | None = None
    coverage: bool = False

    @model_validator(mode="after")
    def _check_probe(self) -> ProbeConfig:
        _check_sv_identifier(self.name, f"probe '{self.name}'")
        if not self.path.strip():
            raise ValueError(
                f"probe '{self.name}': `path` must be a non-empty hierarchical "
                f"reference relative to the DUT instance (e.g. u_core.u_fifo.level)."
            )
        if self.real:
            if (
                self.enum
                or self.type
                or self.packed_dims
                or self.struct
                or self.width != 1
            ):
                raise ValueError(
                    f"probe '{self.name}': `real` is exclusive with "
                    f"width/enum/type/packed_dims/struct."
                )
            if self.coverage:
                raise ValueError(
                    f"probe '{self.name}': a `real` probe cannot set `coverage` — SV "
                    f"forbids a covergroup coverpoint on a real. Assert on it in the "
                    f"probe_sva pragma, or quantize it to an integral field."
                )
        else:
            # Reuse PortConfig's type validation (mutual-exclusion + enum values) —
            # constructing it runs those validators, so type mistakes fail closed here.
            _ = self._as_port
        return self

    @property
    def _as_port(self) -> PortConfig:
        return PortConfig(
            name=self.name,
            width=self.width,
            enum=self.enum,
            type=self.type,
            packed_dims=self.packed_dims,
            struct=self.struct,
        )

    @property
    def is_typed(self) -> bool:
        return (not self.real) and self._as_port.is_typed

    @property
    def if_type(self) -> str:
        """The probe INTERFACE field type. The interface carries RAW bits (like an agent
        interface), so integral probes are `logic [W-1:0]` and the monitor $casts to the
        typed field for symbolic coverage. `real` and an external `type` are declared
        directly (both are assign-compatible with the tapped RTL net)."""
        if self.real:
            return "real"
        if self.type:
            return self.type
        w = self._as_port.bit_width
        return f"logic [{w - 1}:0]" if w > 1 else "logic"

    @property
    def sv_type(self) -> str:
        """The MONITOR typed field (for a symbolic coverpoint / $cast target): the
        enum/struct typedef, the external type, a packed-array logic, or `logic`."""
        if self.real:
            return "real"
        if self.enum:
            return f"{self.name}_e"
        if self.type:
            return self.type
        if self.struct:
            return f"{self.name}_t"
        if self.packed_dims:
            return "logic " + "".join(f"[{d - 1}:0]" for d in self.packed_dims)
        return f"logic [{self.width - 1}:0]" if self.width > 1 else "logic"

    @property
    def needs_cast(self) -> bool:
        """The raw interface bits need a `$cast` into the typed monitor field (enum /
        struct / packed). A plain-width or external-type field is sampled directly."""
        return bool(self.enum or self.struct or self.packed_dims)

    @property
    def struct_typedefs(self) -> list[dict]:
        return [] if self.real else self._as_port.struct_typedefs


class RegressConfig(BaseModel):
    """R1 — regression + coverage-closure infrastructure (opt-in).

    Emits a ``Makefile`` next to the generated sources: elaborate once, then run
    the (test x seed) matrix, verdict each run, and merge + report coverage.
    Absent ⇒ nothing emitted (byte-identical).
    """

    model_config = ConfigDict(extra="forbid")

    # Xcelium only, deliberately. It is the simulator every QuickUVM example is
    # validated on, and the coverage merge/report recipe (imc) is tool-specific.
    # Another tool is a new branch that must be validated end-to-end, not guessed.
    simulator: Literal["xcelium"] = "xcelium"
    # The bench's REAL-RTL filelist, relative to the generated output dir. The
    # generated `run.f` compiles the DUT *stub*, so a regression that drove it
    # would verify nothing — it must point at the bench's own filelist (the
    # hand-written `sim/xrun.f` every example ships).
    filelist: str = "../sim/xrun.f"
    # Default number of seeds per test. A test may override it (TestConfig.seeds).
    seeds: int = 1
    # Emit the coverage collect/merge/report wiring (xrun -coverage + imc).
    coverage: bool = True

    # NB no `goal:` (fail-the-regression-below-N%) yet. It needs a defensible single
    # number to gate on, and imc's text summary is a per-instance table of several
    # metrics — "the first percentage in the report" is not a coverage target. The
    # covergroup-level closure target already exists as V1's `coverage_models[].goal`
    # (option.goal). A real regression-level gate is a follow-up.

    @model_validator(mode="after")
    def _check_regress(self) -> RegressConfig:
        if self.seeds < 1:
            raise ValueError(f"regress.seeds must be >= 1 (got {self.seeds}).")
        if not self.filelist.strip():
            raise ValueError("regress.filelist must be a non-empty path.")
        return self


class AgentRef(BaseModel):
    """F2' — a reference to an agent inside an external, separately-generated VIP. The
    loader resolves `manifest` relative to the consuming config file, reads the named
    agent's spec + the VIP's package filelist, and reconstructs a referenced AgentConfig
    (is_reference=True) that is wired into the env but never regenerated."""

    name: str  # the agent's name inside the VIP (and the local handle prefix)
    manifest: str  # path to the VIP's .qvip manifest, relative to this config file

    @model_validator(mode="after")
    def _check_name(self) -> AgentRef:
        _check_sv_identifier(self.name, "agent_ref name")
        return self


def _resolve_agent_refs(raw: dict, cfg_dir: Path) -> None:
    """F2' — expand `agent_refs:` into referenced agents appended to `agents:`.

    Each ref names an agent inside a VIP manifest (.qvip). This reads the manifest
    (relative to the consuming config file), reconstructs the agent's config, marks it
    is_reference=True, and records the ABSOLUTE path to the VIP's package filelist so
    the generator can chain it with Cadence `-F`. Mutates `raw` in place.
    """
    for ref in raw.get("agent_refs", []):
        name = ref.get("name") if isinstance(ref, dict) else None
        man_rel = ref.get("manifest") if isinstance(ref, dict) else None
        if not name or not man_rel:
            raise ValueError("agent_ref requires both `name` and `manifest`.")
        man_path = (cfg_dir / man_rel).resolve()
        if not man_path.exists():
            raise ValueError(
                f"agent_ref '{name}': VIP manifest not found: {man_path}. "
                f"Generate the VIP first (kind: vip)."
            )
        with open(man_path) as fh:
            manifest = yaml.safe_load(fh) or {}
        agents = manifest.get("agents", {})
        if name not in agents:
            raise ValueError(
                f"agent_ref '{name}': no agent '{name}' in manifest {man_path} "
                f"(has: {sorted(agents)})."
            )
        entry = agents[name]
        if "filelist" not in entry:
            raise ValueError(
                f"agent_ref '{name}': manifest {man_path} entry has no `filelist` "
                f"(a corrupt or hand-edited .qvip)."
            )
        agent_dict = dict(entry.get("config", {}))
        # The consuming bench refers to the agent by the ref NAME (the manifest key), so
        # that authoritative so a hand-edited manifest whose key != config.name still
        # wires the agent under the name the consumer (and env) uses.
        agent_dict["name"] = name
        agent_dict["is_reference"] = True
        agent_dict["ref_filelist"] = str(
            (man_path.parent / entry["filelist"]).resolve()
        )
        raw.setdefault("agents", []).append(agent_dict)


class ProjectConfig(BaseModel):
    project: ProjectMeta
    # F2' — required for an ordinary bench; SYNTHESIZED (name = project name, no RTL
    # emitted) by a before-validator when `vip`/`selftest` is set and no dut given, so
    # the ~40 downstream `self.dut.*` reads never see None. See _synthesize_vip_dut.
    dut: DutConfig
    # M1 — `clock:` accepts a single ClockConfig (today, byte-identical) OR a list of
    # them. A list is split by a before-validator into `clock` (the primary/first, kept
    # for every legacy single-clock read + the -timescale/scoreboard unit) and `clocks`
    # (the full domain list). Read `effective_clocks` in templates.
    clock: ClockConfig = Field(default_factory=ClockConfig)
    clocks: list[ClockConfig] = Field(default_factory=list, exclude=True, repr=False)
    # M1 — externally-generated reset domains (opt-in). Empty ⇒ `effective_resets`
    # synthesizes today's single reset from `dut` (byte-identical).
    resets: list[ResetConfig] = Field(default_factory=list)
    agents: list[AgentConfig] = Field(default_factory=list)
    # F2' — consume agent VIPs BY REFERENCE. Each entry names an agent and a VIP
    # manifest (.qvip); the loader (from_yaml) reads the manifest, reconstructs the
    # agent, marks it is_reference=True, and appends it to `agents` — so it is wired
    # into the env (imported + instantiated) but its source is NOT regenerated. Opt-in,
    # empty ⇒ byte-identical. Requires `layout: packaged`.
    agent_refs: list[AgentRef] = Field(default_factory=list)
    tests: list[TestConfig] = Field(default_factory=lambda: [TestConfig(name="test1")])
    analysis: AnalysisConfig | None = None
    register_model: RegisterModelConfig | None = None
    coverage_models: list[CoverageModel] = Field(default_factory=list)
    # K2 — whitebox probes: OBSERVE-only internal DUT signals (opt-in, byte-identical
    # when empty). See ProbeConfig.
    probes: list[ProbeConfig] = Field(default_factory=list)
    # R1 — regression + coverage-closure runner (opt-in, byte-identical when None).
    # See RegressConfig.
    regress: RegressConfig | None = None
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
    # F2' — GENERATION KIND (mutually exclusive by construction). `bench` (default) is
    # today's path (byte-identical). `vip` emits ONLY the reusable agent VIP(s) — the
    # per-agent packages + filelists + a .qvip manifest — with no DUT, env, test or top.
    # `selftest` emits a DUT-less bench that exercises the VIP against itself (two
    # cross-connected agents). `vip`/`selftest` require `layout: packaged`.
    kind: Literal["bench", "vip", "selftest"] = "bench"
    # Name of the generated top module + file: `module <top_name>;` in <top_name>.sv,
    # and the elaboration `-top`. Default "tb_top" (byte-identical); set to e.g. "tb"
    # for the OpenTitan/uvmdvgen convention. NB: a hand-authored sim wrapper that
    # references tb_top.sv / `-top tb_top` must be updated to match when this changes.
    top_name: str = "tb_top"
    # H1 — sub-environments. When set, this is a subsystem (top) bench that
    # composes >=2 child block envs (each referenced by config path) instead of
    # defining its own agents. Opt-in: empty → an ordinary bench (byte-identical).
    subenvs: list[SubenvConfig] = Field(default_factory=list)
    # H1 cross-block — top-level wires between composed blocks (source block output
    # -> destination block input) and cross-block scoreboards (predict the monitor
    # block's output from the source block's stream). Only valid with `subenvs`.
    connections: list[SubenvConnection] = Field(default_factory=list)
    subenv_scoreboards: list[SubenvScoreboard] = Field(default_factory=list)
    # Runtime: the loaded child ProjectConfigs, keyed by subenv name. Populated by
    # the loader (which resolves `subenv.config` relative to the top file); not
    # part of the serialized config.
    subenv_configs: dict[str, ProjectConfig] = Field(
        default_factory=dict, exclude=True, repr=False
    )
    # Runtime: the applied class-name prefix per subenv ("" = not namespaced),
    # populated by the loader. Read by SubenvView (namespaced / dut_module).
    subenv_namespaces: dict[str, str] = Field(
        default_factory=dict, exclude=True, repr=False
    )
    # Runtime: the block's ORIGINAL dut.name (the real RTL module), captured before
    # any namespace prefix is applied — so a reused block's DUT is instantiated at
    # its true unprefixed module name however many prefixes stack. "" = never
    # prefixed (dut_module falls through to dut.name).
    original_dut_name: str = Field(default="", exclude=True, repr=False)

    @model_validator(mode="before")
    @classmethod
    def _synthesize_vip_dut(cls, data: object) -> object:
        """F2' — a VIP / self-test has no DUT. Rather than make `dut` Optional (which
        would NPE ~40 downstream `self.dut.*` reads), synthesize a nameplate DutConfig
        (name = project name) when `kind` is vip/selftest and no dut is given. No DUT
        module is emitted (the vip/selftest generator path skips the stub). An ordinary
        bench is untouched (byte-identical)."""
        if isinstance(data, dict) and data.get("kind") in ("vip", "selftest"):
            if not data.get("dut"):
                proj = data.get("project") or {}
                name = proj.get("name") if isinstance(proj, dict) else None
                data["dut"] = {"name": name or "vip", "combinational": True}
        return data

    @model_validator(mode="before")
    @classmethod
    def _split_clock_list(cls, data: object) -> object:
        """M1 — accept `clock:` as either a single mapping (today) or a LIST of them.
        A list is split into `clocks` (the full domain list) + `clock` (the primary /
        first, for every legacy single-clock read). A scalar leaves `clocks` empty, so a
        single-clock bench is byte-identical."""
        if isinstance(data, dict) and isinstance(data.get("clock"), list):
            clocks = data["clock"]
            data = {**data, "clocks": clocks, "clock": (clocks[0] if clocks else {})}
        return data

    @field_serializer("clock")
    def _ser_clock(self, clock: ClockConfig, _info: object) -> object:
        """Round-trip the union: dump `clock` as the full list when multi-clock (so a
        dumped config reloads with every domain — `clocks` is derived + excluded), else
        the single mapping (a single-clock dump is byte-identical)."""
        if self.clocks:
            return [c.model_dump() for c in self.clocks]
        return clock.model_dump()

    # ---- M1 multi-clock / multi-reset — resolvers (single-domain → byte-identical) --

    @model_validator(mode="after")
    def _check_observed_clocks(self) -> ProjectConfig:
        """Fail-closed rules for a clock the DUT drives (`source: dut`).

        Getting this wrong produces a bench that RUNS, PASSES, and MEASURES NOTHING, so
        every one of these is an error rather than a warning.
        """
        clocks = self.effective_clocks
        observed = [c for c in clocks if c.observed]
        if not observed:
            return self

        driven = [c for c in clocks if not c.observed]
        if not driven:
            raise ValueError(
                "clock: every clock is `source: dut`, so the TB generates no clock at "
                "all. A test's run length is measured in TB clock edges; with none, a "
                "DUT that never toggles its clock would HANG rather than fail, and a "
                "hung bench cannot report an error. Declare at least one TB-driven "
                "clock."
            )

        for c in observed:
            if c.name == self.dut.clock:
                raise ValueError(
                    f"clock '{c.name}': `source: dut` names the DUT's own CLOCK INPUT "
                    f"(dut.clock). A DUT cannot both consume this clock and generate "
                    f"it. "
                    f"An observed clock is a DUT OUTPUT (an SPI sck, an I2C scl)."
                )
            for r in self.effective_resets:
                if r.clock == c.name:
                    raise ValueError(
                        f"reset '{r.name}' is synced to '{c.name}', which is `source: "
                        f"dut`. The TB cannot deassert a reset synchronously to a "
                        f"clock "
                        f"the DUT only starts driving once it is out of reset — that "
                        f"is "
                        f"a deadlock. Sync the reset to a TB-driven clock."
                    )
        return self

    @property
    def primary_clock_observed(self) -> bool:
        """Is the clock a responder-only test would count edges on DUT-driven?

        If so the test must not count its edges at all: an observed clock is usually
        GATED (an SPI sck ticks only inside a frame), and a DUT that never drives it
        would HANG the test rather than fail it.
        """
        ag = self.primary_agent
        if ag is None:
            return False
        name = ag.clock or (
            self.effective_clocks[0].name if self.effective_clocks else ""
        )
        return any(c.name == name and c.observed for c in self.effective_clocks)

    @property
    def primary_clock_period_ts(self) -> int:
        """The primary agent's clock period, in timescale units."""
        ag = self.primary_agent
        clocks = self.effective_clocks
        if ag is None or not clocks:
            return 10
        name = ag.clock or clocks[0].name
        c = next((c for c in clocks if c.name == name), clocks[0])
        return self.clock_period_ts(c)

    @property
    def observed_clocks(self) -> list[ClockConfig]:
        return [c for c in self.effective_clocks if c.observed]

    @property
    def effective_clocks(self) -> list[ClockConfig]:
        """Every clock domain: the `clocks` list, or `[self.clock]` for a single-clock
        bench (whose sole clock is named `clk` — byte-identical)."""
        return self.clocks if self.clocks else [self.clock]

    @property
    def timescale_unit(self) -> str:
        """M1 mixed-unit — the single `-timescale` unit: the FINEST (smallest) unit
        across all clocks. With one unit it is that unit (byte-identical; no lookup)."""
        units = {c.unit for c in self.effective_clocks}
        if len(units) == 1:
            return next(iter(units))
        return min(units, key=lambda u: _UNIT_MAG[u])

    def clock_period_ts(self, clock: ClockConfig) -> int:
        """`clock`'s period expressed in the `timescale_unit` (so `#delay` cadence /
        drive skew are correct under one -timescale). When the clock's unit IS the
        timescale unit (every single-unit bench) this returns the period unchanged."""
        ts = self.timescale_unit
        if clock.unit == ts:
            return clock.period
        return clock.period * (_UNIT_MAG[clock.unit] // _UNIT_MAG[ts])

    @property
    def subsystem_timescale_unit(self) -> str:
        """M1 clocked-subenv — the `-timescale` unit for a SUBSYSTEM tb_top: the single
        (validated) time unit shared by its clocked leaves, so a non-`ns` clocked
        subsystem needn't have the combinational top redundantly declare a clock. No
        clocked leaves → the top's own `timescale_unit` (byte-identical)."""
        units = {
            lv.sv.cfg.effective_clocks[0].unit for lv in self.leaf_views if lv.clocked
        }
        return next(iter(units)) if len(units) == 1 else self.timescale_unit

    @property
    def effective_resets(self) -> list[ResetConfig]:
        """Every externally-generated reset domain: the `resets` list, or a single
        reset synthesized from `dut` when a single external reset is configured. Empty
        when the reset is agent-driven / the DUT is combinational (no top generator)."""
        if self.resets:
            return self.resets
        # (validate_dut already rejects external_reset without a reset name, so the
        # `and self.dut.reset` guard here is belt-and-suspenders.)
        if self.dut.external_reset and self.dut.reset:
            return [
                ResetConfig(
                    name=self.dut.reset,
                    active_low=self.dut.reset_active_low,
                    clock=self.effective_clocks[0].name,
                )
            ]
        return []

    @property
    def has_probes(self) -> bool:
        return bool(self.probes)

    @property
    def probe_clock(self) -> str:
        """The clock net the probe interface samples on. MVP = one probe clocking
        domain: every probe's `clock` (if set) must agree; unset ⇒ the sole/first clock
        (validated in validate_probes)."""
        named = {p.clock for p in self.probes if p.clock}
        if named:
            return next(iter(named))
        return self.effective_clocks[0].name

    @property
    def probe_reset(self) -> ResetConfig | None:
        """The reset bound to the probe clock (for `disable iff` in probe SVA), or None
        (combinational / agent-driven reset)."""
        return next(
            (r for r in self.effective_resets if r.clock == self.probe_clock),
            self.effective_resets[0] if self.effective_resets else None,
        )

    def agent_clock(self, agent: AgentConfig) -> ClockConfig:
        """The clock domain an agent runs on — its named `clock`, or the sole/first."""
        if agent.clock:
            return next(
                (c for c in self.effective_clocks if c.name == agent.clock),
                self.effective_clocks[0],
            )
        return self.effective_clocks[0]

    def agent_reset(self, agent: AgentConfig) -> ResetConfig | None:
        """The external reset an agent gates on — its named `reset`, else the reset
        bound to its clock domain, else the first; None when no external reset."""
        resets = self.effective_resets
        if not resets:
            return None
        if agent.reset:
            return next((r for r in resets if r.name == agent.reset), resets[0])
        ac = self.agent_clock(agent).name
        return next((r for r in resets if r.clock == ac), resets[0])

    def agent_driven_reset(self, agent: AgentConfig) -> DrivenReset | None:
        """M1 — this agent's AGENT-DRIVEN reset (name + polarity) that its own sequences
        drive, or None. Only for the agent-driven path (no top reset generator): None
        when the reset is EXTERNAL (`dut.external_reset`) or the DUT has no reset.
        `reset_port` names the agent's own reset input port; when unset it falls back to
        the port named `dut.reset` if the agent has one (byte-identical). Polarity is
        `reset_port_active_low`, else the global `dut.reset_active_low`."""
        if self.dut.external_reset or not self.dut.reset:
            return None
        name = agent.reset_port or self.dut.reset
        if not any(p.name == name for p in agent.input_ports):
            return None
        active_low = (
            agent.reset_port_active_low
            if agent.reset_port_active_low is not None
            else self.dut.reset_active_low
        )
        return DrivenReset(name=name, active_low=active_low)

    @property
    def subenv_views(self) -> list[SubenvView]:
        """H1 — the composed child block envs (in `subenvs` order), once their
        configs are loaded; empty for an ordinary bench."""
        return [
            SubenvView(
                s.name,
                self.subenv_configs[s.name],
                self.subenv_namespaces.get(s.name, ""),
            )
            for s in self.subenvs
            if s.name in self.subenv_configs
        ]

    # ---- H1 nested — recursive tree walks (flat single-level → byte-identical) --

    @property
    def leaf_views(self) -> list[LeafView]:
        """Every LEAF block (subenv with no subenvs), depth-first, each carrying its
        path of subenv names. For tb_top. At depth 1 the path is (name,), so
        pathname == subenv name (byte-identical to the flat wiring)."""
        out: list[LeafView] = []

        def walk(cfg: ProjectConfig, path: list[str]) -> None:
            for sv in cfg.subenv_views:
                if sv.is_subsystem:
                    walk(sv.cfg, path + [sv.name])
                else:
                    out.append(LeafView(sv, path + [sv.name]))

        walk(self, [])
        return out

    @property
    def config_build_ops(self) -> list[dict]:
        """Pre-order config-tree build ops for the top base_test: create each level's
        env_cfg into its parent field, populate leaf agent cfgs (+ vif by full-path
        key), and set each level's cfg into the config DB at its absolute path. At
        depth 1 this degenerates to the flat per-child loop (byte-identical)."""
        ops: list[dict] = []

        def walk(cfg: ProjectConfig, field: str, dbpath: str, path: list[str]) -> None:
            for sv in cfg.subenv_views:
                f = f"{field}.{sv.cfg_field}"
                p = f"{dbpath}.{sv.name}"
                npath = path + [sv.name]
                agents: list[tuple[AgentConfig, str]] = []
                if not sv.is_subsystem:
                    for a in sv.agents:
                        vkey = "_".join(npath) + f"_{a.interface}_vif"
                        agents.append((a, vkey))
                ops.append(
                    {
                        "name": sv.name,
                        "block": sv.block,
                        "field": f,
                        "create_name": sv.cfg_field,
                        "cfg_class": sv.env_cfg_class,
                        "agents": agents,
                        "db_path": p,
                    }
                )
                if sv.is_subsystem:
                    walk(sv.cfg, f, p, npath)

        walk(self, "env_cfg", "e", [])
        return ops

    @property
    def composition_levels(self) -> list[ProjectConfig]:
        """Every subsystem config (nested clusters + this top), DEEPEST-FIRST — the
        order the top test_pkg must include the composition classes. Flat → [self]."""
        out: list[ProjectConfig] = []

        def walk(cfg: ProjectConfig) -> None:
            for sv in cfg.subenv_views:
                if sv.is_subsystem:
                    walk(sv.cfg)
            out.append(cfg)  # post-order: deeper levels before this one

        walk(self)
        return out

    @property
    def leaf_env_pkgs(self) -> list[str]:
        """All leaf blocks' env packages (flattened). Flat → direct children."""
        return [lv.sv.env_pkg for lv in self.leaf_views]

    @property
    def leaf_agent_pkgs(self) -> list[str]:
        """All leaf blocks' agent VIP packages (flattened)."""
        return [f"{a.name}_pkg" for lv in self.leaf_views for a in lv.agents]

    def _resolve_endpoint(
        self, ref: str, what: str
    ) -> tuple[list[str], str, ProjectConfig]:
        """Resolve a dotted connection/scoreboard endpoint RELATIVE TO THIS LEVEL to
        `(block_path, item, leaf_cfg)`: the path of subenv names descended to reach a
        LEAF block, the trailing port/agent name, and that leaf's config. At depth 1
        (`<block>.<item>`) the block_path is `[block]` — byte-identical to the flat
        cross-block case. The path descends by subenv INSTANCE name (preserved under
        reuse), so it addresses a leaf inside a reused (namespaced) subtree too; the
        trailing agent token is the ORIGINAL name (the resolver maps it to the prefixed
        handle — see `_leaf_agent`). Fail-closed on an unknown segment, descending into
        a leaf, or a non-leaf final segment."""
        parts = ref.split(".")
        if len(parts) < 2:
            raise ValueError(
                f"{what} '{ref}' must name a block and a port/agent — "
                f"'<block>.<name>', or '<subsystem>...<block>.<name>' to reach a leaf "
                f"block inside a nested subsystem."
            )
        *blk_path, item = parts
        cfg: ProjectConfig = self
        for i, seg in enumerate(blk_path):
            views = {sv.name: sv for sv in cfg.subenv_views}
            sv = views.get(seg)
            if sv is None:
                loc = f"'{'.'.join(blk_path[:i])}'" if i else "the composed blocks"
                raise ValueError(
                    f"{what} '{ref}' references unknown block '{seg}' in {loc}."
                )
            if i < len(blk_path) - 1:
                if not sv.is_subsystem:
                    rest = ".".join(blk_path[i + 1 :])
                    raise ValueError(
                        f"{what} '{ref}': '{seg}' is a leaf block, not a subsystem — "
                        f"cannot descend into it to reach '{rest}'."
                    )
                cfg = sv.cfg
            else:
                if sv.is_subsystem:
                    raise ValueError(
                        f"{what} '{ref}': block '{seg}' is a subsystem, not a leaf — "
                        f"descend to an inner leaf block, e.g. "
                        f"'{seg}.<inner-block>.{item}'."
                    )
                return blk_path, item, sv.cfg
        raise AssertionError("unreachable")  # pragma: no cover

    def _iface_signal(self, ref: str, prefix: tuple[str, ...] = ()) -> str:
        """Resolve a `<block>...<port>` reference to the flattened tb_top interface
        signal `<path>_<iface>_inst.<port>`, where `<path>` is `prefix` (the declaring
        level's path from the top) joined with the endpoint's own block path. At the
        top with a flat `<block>.<port>` this is `<block>_<iface>_inst.<port>`
        (byte-identical). `prefix` is empty for a top-declared wire."""
        blk_path, port, cfg = self._resolve_endpoint(ref, "connection")
        full = list(prefix) + blk_path
        for a in cfg.agents:
            if any(p.name == port for _, p in a.all_ports):
                return f"{'_'.join(full)}_{a.interface}_inst.{port}"
        return ref  # unreachable — validated in validate_subenv_composition

    @property
    def resolved_connections(self) -> list[dict[str, str]]:
        """H1 — this level's own cross-block wires as interface signals (dst driven by
        src), resolved relative to this level. For the flattened tb_top assigns use
        `all_resolved_connections`."""
        return [
            {"dst": self._iface_signal(c.dst), "src": self._iface_signal(c.src)}
            for c in self.connections
        ]

    @property
    def all_resolved_connections(self) -> list[dict[str, str]]:
        """H1 nested — EVERY cross-block wire in the whole tree (this level + every
        nested cluster), each resolved to its flattened tb_top signal name (prefixed
        by the declaring level's path from the top). This is what tb_top emits as
        `assign dst = src;`. Flat single-level → identical to resolved_connections."""
        out: list[dict[str, str]] = []

        def walk(cfg: ProjectConfig, prefix: tuple[str, ...]) -> None:
            for c in cfg.connections:
                out.append(
                    {
                        "dst": cfg._iface_signal(c.dst, prefix),
                        "src": cfg._iface_signal(c.src, prefix),
                    }
                )
            for sv in cfg.subenv_views:
                if sv.is_subsystem:
                    walk(sv.cfg, prefix + (sv.name,))

        walk(self, ())
        return out

    def cross_block_sb_endpoints(
        self, sb: SubenvScoreboard
    ) -> tuple[str, AgentConfig, str, AgentConfig]:
        """(source-handle-chain, source-agent, monitor-handle-chain, monitor-agent)
        for a cross-block scoreboard declared at THIS level. The handle chain is the
        dotted path of child-env handles from this level's env down to the leaf
        (e.g. 'stg1.add'); the scoreboard's connect_phase reaches the leaf agent's
        analysis port through it. Flat same-level → a single handle (byte-identical)."""
        spath, sag, scfg = self._resolve_endpoint(sb.source, "cross-block scoreboard")
        mpath, mag, mcfg = self._resolve_endpoint(sb.monitor, "cross-block scoreboard")
        sagent = _leaf_agent(scfg, sag)
        magent = _leaf_agent(mcfg, mag)
        if sagent is None or magent is None:  # pragma: no cover
            # unreachable: validate_subenv_composition rejects a missing agent (with a
            # clear message) before generation ever calls this.
            raise AssertionError("unvalidated cross-block scoreboard endpoint")
        return ".".join(spath), sagent, ".".join(mpath), magent

    def validate_subenv_composition(self) -> None:
        """Cross-child checks run by the loader once child configs are loaded.
        The composed blocks share one output directory + package namespace, so
        their class/file names must not collide, and each must be a composable
        block (no nested subenvs / register model in this slice)."""
        duts: set[str] = {self.dut.name}
        ifaces: set[str] = set()
        items: set[str] = set()
        anames: set[str] = set()
        seqs: set[str] = set()
        for s in self.subenvs:
            child = self.subenv_configs.get(s.name)
            if child is None:
                raise ValueError(f"subenv '{s.name}': child config not loaded.")
            # H1 nested — a child that is itself a subsystem is composed recursively
            # (its own validate_subenv_composition already ran via from_yaml).
            # Reusing (namespacing) and parameterizing a nested subsystem ARE now
            # supported (the prefix + param overrides recurse down the subtree in
            # from_yaml); the flattened-uniqueness guard below is the safety net.
            if child.register_model is not None:
                raise ValueError(
                    f"subenv '{s.name}': a child block with a register_model is not "
                    f"supported in a subsystem yet."
                )
            if not child.dut.combinational:
                # Clocked child (a registered, typically external-reset block): the
                # subenv tb_top generates a per-leaf clock + reset with pathname-
                # prefixed nets (M1). For this slice a composed clocked block must be
                # single-clock / at-most-one-reset (nested multi-clock leaves are a
                # later slice); cross-leaf time-unit agreement is checked below.
                if len(child.effective_clocks) != 1:
                    raise ValueError(
                        f"subenv '{s.name}': a composed clocked block must be single-"
                        f"clock (a nested multi-clock leaf is not supported yet)."
                    )
                if len(child.effective_resets) > 1:
                    raise ValueError(
                        f"subenv '{s.name}': a composed clocked block must have at "
                        f"most one reset (multiple leaf resets not supported yet)."
                    )
            if any(a.parameters for a in child.agents) and len(child.agents) > 1:
                raise ValueError(
                    f"subenv '{s.name}': a parameterized child block must be "
                    f"single-agent (the block DUT's #() args are taken from the sole "
                    f"agent's parameters)."
                )
            if child.dut.name in duts:
                hint = ""
                if s.namespace is False:
                    hint = (
                        " (namespacing is disabled on this reused block — remove "
                        "`namespace: false` or give it a distinct prefix)"
                    )
                raise ValueError(
                    f"subenv '{s.name}': block name '{child.dut.name}' (dut.name) "
                    f"collides with another block or the top — each must be "
                    f"unique{hint}."
                )
            duts.add(child.dut.name)
            for a in child.agents:
                axes = [
                    (anames, a.name, "agent name"),
                    (ifaces, a.interface, "interface"),
                    (items, a.sequence_item, "sequence_item"),
                ]
                axes += [(seqs, sq.name, "sequence") for sq in a.sequences]
                for coll, val, what in axes:
                    if val in coll:
                        raise ValueError(
                            f"subenv '{s.name}': {what} '{val}' collides with another "
                            f"block — composed blocks share a namespace, so agent "
                            f"names/interfaces/transactions/sequences must be unique "
                            f"across them."
                        )
                    coll.add(val)

        # M1 clocked-subenv — every CLOCKED composed block must share one time unit
        # (the flattened tb_top emits a single -timescale). The subsystem's timescale
        # is that shared leaf unit (see subsystem_timescale_unit); mixed units across
        # leaves are a later slice.
        clocked_units = {
            lv.sv.cfg.effective_clocks[0].unit for lv in self.leaf_views if lv.clocked
        }
        if len(clocked_units) > 1:
            raise ValueError(
                "clocked composed blocks must share one time unit (the subsystem "
                f"tb emits one -timescale) — found {sorted(clocked_units)}."
            )

        # H1 nested — the WHOLE flattened tree shares the top package namespace, so
        # every subsystem prefix + every leaf's block/agent/interface/transaction name
        # AND every leaf's flattened pathname (which prefixes its tb_top interface / DUT
        # / clock-net identifiers) must be unique across the tree (the per-level loop
        # only sees direct children). Runs only when there is nesting; flat → no-op.
        if any(sv.is_subsystem for sv in self.subenv_views):
            tree: dict[str, str] = {}

            def _claim(name: str, what: str) -> None:
                if name in tree:
                    raise ValueError(
                        f"nested: {what} '{name}' collides with another name "
                        f"({tree[name]}) elsewhere in the tree — every subsystem/"
                        f"block/agent/interface/transaction name must be unique "
                        f"across the composed hierarchy."
                    )
                tree[name] = what

            _claim(self.dut.name, "top name")
            for level in self.composition_levels:
                if level is not self:
                    _claim(level.dut.name, "subsystem name")
            for lv in self.leaf_views:
                _claim(lv.sv.block, "block name")
                for a in lv.agents:
                    _claim(a.name, "agent name")
                    _claim(a.interface, "interface")
                    _claim(a.sequence_item, "transaction")
            # Two distinct leaves can flatten to the SAME pathname (e.g. leaf `a_b` vs
            # subsystem `a` → leaf `b`), which would emit duplicate tb_top instance /
            # net identifiers — fail closed.
            paths: dict[str, str] = {}
            for lv in self.leaf_views:
                if lv.pathname in paths:
                    raise ValueError(
                        f"nested: two composed leaves flatten to the same path-"
                        f"prefixed name '{lv.pathname}' — rename a subenv so every "
                        f"leaf's flattened path is unique."
                    )
                paths[lv.pathname] = lv.sv.block

        # H1 cross-block — validate connection + scoreboard endpoints. Endpoints are
        # dotted paths resolved relative to THIS level (each level validates its own
        # connections/scoreboards), so a path may descend into a nested subsystem to a
        # leaf block (cross-level); _resolve_endpoint fails closed on a bad path.
        seen_dst: set[str] = set()
        for c in self.connections:
            spath, sport, scfg = self._resolve_endpoint(c.src, "connection 'from'")
            dpath, dport, dcfg = self._resolve_endpoint(c.dst, "connection 'to'")
            sblk, dblk = spath[-1], dpath[-1]
            sportc = next(
                (p for a in scfg.agents for p in a.output_ports if p.name == sport),
                None,
            )
            if sportc is None:
                raise ValueError(
                    f"connection 'from' '{c.src}': '{sport}' is not an output port "
                    f"of block '{sblk}'."
                )
            dagent = next(
                (a for a in dcfg.agents for p in a.input_ports if p.name == dport),
                None,
            )
            if dagent is None:
                raise ValueError(
                    f"connection 'to' '{c.dst}': '{dport}' is not an input port of "
                    f"block '{dblk}'."
                )
            if dagent.active:
                raise ValueError(
                    f"connection 'to' '{c.dst}': block '{dblk}' agent "
                    f"'{dagent.name}' is active and would drive '{dport}', "
                    f"conflicting with the connection — make it passive "
                    f"(active: false)."
                )
            dportc = next(p for p in dagent.input_ports if p.name == dport)
            if sportc.bit_width != dportc.bit_width:
                raise ValueError(
                    f"connection '{c.src}' -> '{c.dst}': width mismatch "
                    f"({sportc.bit_width}-bit output driving a {dportc.bit_width}-bit "
                    f"input) — would silently truncate/pad."
                )
            # key single-driver on the CANONICAL resolved destination path, so two
            # spellings of the same nested input can't both drive it.
            dkey = ".".join(dpath + [dport])
            if dkey in seen_dst:
                raise ValueError(
                    f"connection: multiple connections drive '{c.dst}' (a port can "
                    f"have only one driver)."
                )
            seen_dst.add(dkey)

        # Cross-level: the per-level seen_dst above only sees THIS level's wires, but a
        # nested leaf input can be driven by wires declared at different levels (a
        # cluster's own internal wire and an ancestor's cross-level wire), spelled
        # differently relative to each level. Guard driver-uniqueness on the fully
        # resolved tb_top signal (the physical net), which collapses every spelling of
        # one leaf input to a single string. Runs at the level that sees the whole
        # subtree (the top); empty / flat → no-op.
        resolved_dst: set[str] = set()
        for rc in self.all_resolved_connections:
            if rc["dst"] in resolved_dst:
                raise ValueError(
                    f"connection: multiple connections drive '{rc['dst']}' (a port can "
                    f"have only one driver) — a cross-level wire targets a leaf input "
                    f"that another level's wire already drives."
                )
            resolved_dst.add(rc["dst"])

        sbnames = [sb.name for sb in self.subenv_scoreboards]
        if len(sbnames) != len(set(sbnames)):
            raise ValueError("cross-block scoreboard names must be unique.")
        for sb in self.subenv_scoreboards:
            for role, ref in (("source", sb.source), ("monitor", sb.monitor)):
                blk_path, agent, cfg = self._resolve_endpoint(
                    ref, f"cross-block scoreboard '{sb.name}' {role}"
                )
                if _leaf_agent(cfg, agent) is None:
                    raise ValueError(
                        f"cross-block scoreboard '{sb.name}' {role} '{ref}': block "
                        f"'{blk_path[-1]}' has no agent '{agent}'."
                    )

    @field_validator("top_name")
    @classmethod
    def _check_top_name(cls, v: str) -> str:
        # It becomes `module <top_name>;` + the `-top` elaboration target, so it must
        # be a legal, non-reserved SystemVerilog identifier.
        _check_sv_identifier(v, "top_name")
        return v

    @model_validator(mode="after")
    def validate_regress(self) -> ProjectConfig:
        if self.regress is None:
            return self
        # H1 deferred: a subsystem's leaf RTL is listed by hand inside the
        # `subenv_dut_sources` pragma, so the generator cannot know the bench's real
        # filelist — and `make regress` must drive real RTL, not the DUT stub.
        if self.subenvs:
            raise ValueError(
                "`regress` is not yet supported on a subsystem bench (`subenvs`): the "
                "leaf RTL sources live in a `subenv_dut_sources` pragma region, so "
                "the generator cannot derive the real-RTL filelist a regression must "
                "drive. Run the leaf blocks' own regressions, or drive it by hand."
            )
        names = [j["name"] for j in self.regress_jobs]
        if not names:
            raise ValueError(
                "`regress` needs at least one runnable test, but the testlist is empty "
                "(no `tests:`, no RAL `reg_test`, no `csr_tests`). A regression that "
                "runs nothing would report success."
            )
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(
                f"`regress` testlist has duplicate +UVM_TESTNAME entries: {dupes}. Two "
                f"`tests:` share a name, or a declared test collides with a generated "
                f"RAL/CSR test (the RAL basic test's class is the bare `reg_test`). "
                f"Rename it."
            )
        return self

    @model_validator(mode="after")
    def validate_probes(self) -> ProjectConfig:
        if not self.probes:
            return self
        # H1 deferred: probe paths are relative to ONE DUT instance; a subsystem bench
        # has per-leaf DUTs — probe the leaf block's own config instead.
        if self.subenvs:
            raise ValueError(
                "whitebox `probes` are not yet supported on a subsystem bench "
                "(`subenvs`): paths are relative to one DUT instance, but a composed "
                "bench has per-leaf DUTs. Probe the leaf block's own config instead."
            )
        if any(a.instances for a in self.agents):
            raise ValueError(
                "whitebox `probes` are not yet supported with multi-instantiated "
                "agents (`instances`): there is no single DUT instance to resolve "
                "paths against."
            )
        pnames = [p.name for p in self.probes]
        if len(pnames) != len(set(pnames)):
            raise ValueError("probe names must be unique.")
        # No collision with agent port / interface / clock / reset nets — they share the
        # tb_top + config-DB namespace with the probe interface and its signals.
        reserved: dict[str, str] = {}
        for a in self.agents:
            reserved.setdefault(a.interface, f"agent '{a.name}' interface")
            for _kind, port in a.all_ports:
                reserved.setdefault(port.name, f"agent '{a.name}' port")
        for c in self.effective_clocks:
            reserved.setdefault(c.name, "a clock net")
        for r in self.effective_resets:
            reserved.setdefault(r.name, "a reset net")
        clock_names = {c.name for c in self.effective_clocks}
        for p in self.probes:
            if p.name in reserved:
                raise ValueError(
                    f"probe '{p.name}' collides with {reserved[p.name]} — probe names "
                    f"share the tb_top / config-DB namespace; rename the probe."
                )
            if p.clock is not None and p.clock not in clock_names:
                raise ValueError(
                    f"probe '{p.name}': clock '{p.clock}' is not a declared clock "
                    f"(have {sorted(clock_names)})."
                )
        set_clocks = {p.clock for p in self.probes if p.clock}
        if len(set_clocks) > 1:
            raise ValueError(
                f"probes span multiple clock domains {sorted(set_clocks)} — the probe "
                f"interface has ONE clocking block for now; put them on a single "
                f"`clock:` (multi-domain probes are a follow-up)."
            )
        return self

    @model_validator(mode="after")
    def validate_count(self) -> ProjectConfig:
        """I-9 — `count` is a focused first slice (a single-agent, single-clock,
        external-reset, initiator array with plain single-stream scoreboards). The
        shared-DUT wiring reuses the C3 per-instance env path, which does NOT wire a
        second agent, coverage, inouts, multi-clock, or a customized scoreboard — so
        REJECT those combinations LOUDLY here rather than silently mis-generate."""
        count_agents = [a for a in self.agents if a.count > 1]
        if not count_agents:
            return self
        if len(count_agents) > 1:
            raise ValueError("at most one agent may use `count` per bench.")
        ca = count_agents[0]
        if len(self.agents) != 1:
            raise ValueError(
                f"`count` (agent '{ca.name}') requires it be the SOLE agent for now — "
                f"the shared-vectored-DUT wiring does not yet compose a count array "
                f"with other agents (alert_handler's N alerts + tl_agent: follow-up)."
            )
        if self.clocks or self.resets:
            raise ValueError(
                f"`count` (agent '{ca.name}') is not yet supported with multi-clock/"
                f"reset (`clock:`/`resets:` lists) — the shared-DUT array is 1-domain."
            )
        if not self.dut.external_reset:
            raise ValueError(
                f"`count` (agent '{ca.name}') requires `dut.external_reset: true` — a "
                f"shared vectored DUT binds the top-level reset net."
            )
        if ca.inout_ports:
            raise ValueError(
                f"`count` (agent '{ca.name}') does not yet support `inouts` — the "
                f"shared-DUT wiring vectors inputs/outputs only."
            )
        _cov = self.analysis is not None and self.analysis.coverage
        if _cov or self.coverage_models:
            raise ValueError(
                f"`count` (agent '{ca.name}') does not yet wire coverage — the "
                f"per-instance env path omits the collectors (declare it on a "
                f"non-count bench for now)."
            )
        if self.analysis is not None:
            for s in self.analysis.scoreboards:
                if (
                    s.monitor
                    or s.window
                    or s.match != "in_order"
                    or s.match_key
                    or s.max_latency
                ):
                    raise ValueError(
                        f"`count` (agent '{ca.name}'): scoreboard '{s.name}' must be a "
                        f"plain single-stream scoreboard — a windowed/two-stream/"
                        f"out-of-order one is flattened per-instance, dropping its "
                        f"customization."
                    )
        return self

    @model_validator(mode="after")
    def validate_agents(self) -> ProjectConfig:
        names = [a.name for a in self.agents]
        if len(names) != len(set(names)):
            raise ValueError("Agent names must be unique.")
        if not self.subenvs and (self.connections or self.subenv_scoreboards):
            raise ValueError(
                "`connections` / `subenv_scoreboards` are only valid on a subsystem "
                "bench (they wire/scoreboard composed `subenvs`)."
            )
        if self.subenvs:
            if self.agents:
                raise ValueError(
                    "a bench with `subenvs` composes child block envs and must not "
                    "define its own `agents` (this slice)."
                )
            if self.layout != "packaged":
                raise ValueError(
                    "`subenvs` require `layout: packaged` (each child block is a "
                    "reusable env package that the top composes)."
                )
            snames = [s.name for s in self.subenvs]
            if len(snames) != len(set(snames)):
                raise ValueError("subenv names must be unique.")
            if len(self.subenvs) < 2:
                raise ValueError(
                    "a subsystem bench composes >=2 child block envs "
                    "(declare at least two `subenvs`)."
                )
            if (
                self.analysis is not None
                or self.register_model is not None
                or self.coverage_models
            ):
                raise ValueError(
                    "a `subenvs` top must not set analysis/register_model/"
                    "coverage_models (this slice) — those belong on the child blocks."
                )
        elif not self.agents:
            raise ValueError("At least one agent must be defined.")
        # F2' — VIP / self-test / by-reference need the packaged layout: a VIP is
        # per-agent packages, and flat folds everything into one tb_pkg (nothing to
        # reuse or reference).
        if self.kind != "bench" and self.layout != "packaged":
            raise ValueError(
                f"`kind: {self.kind}` requires `layout: packaged` (a VIP is per-agent "
                f"packages; flat has no package to reuse)."
            )
        if (self.agent_refs or any(a.is_reference for a in self.agents)) and (
            self.layout != "packaged"
        ):
            raise ValueError(
                "consuming an agent by reference (`agent_refs`) requires "
                "`layout: packaged` — the referenced VIP is an external package."
            )
        # `agent_refs` are resolved by from_yaml (which reads the manifest relative to
        # the config file). A bare model_validate can't do that file I/O, so a config
        # with unresolved refs would generate NOTHING for them — fail loudly instead.
        if self.agent_refs and not any(a.is_reference for a in self.agents):
            raise ValueError(
                "`agent_refs` were not resolved — load this config via "
                "ProjectConfig.from_yaml (it reads each VIP manifest relative to "
                "the config file); a bare model_validate cannot resolve them."
            )
        if self.is_vip and (
            self.subenvs or self.register_model is not None or self.connections
        ):
            raise ValueError(
                "`kind: vip` emits only reusable agent packages — it must not set "
                "`subenvs` / `register_model` / `connections`."
            )
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
                # Windowed scoreboard: the boundary strobe must be a 1-bit OUTPUT port
                # of the source agent (predict() keys the per-window verdict off
                # `t.<boundary>`), and the reference model is SystemVerilog.
                if s.window is not None:
                    src = next(a for a in self.agents if a.name == s.source)
                    bport = next(
                        (p for p in src.output_ports if p.name == s.window.boundary),
                        None,
                    )
                    if bport is None:
                        raise ValueError(
                            f"analysis.scoreboards '{s.name}': window.boundary "
                            f"'{s.window.boundary}' is not an output port of source "
                            f"agent '{s.source}' (it must be the DUT strobe closing "
                            f"a window)."
                        )
                    if (
                        bport.bit_width != 1
                        or bport.struct is not None
                        or bport.packed_dims is not None
                    ):
                        raise ValueError(
                            f"analysis.scoreboards '{s.name}': window.boundary "
                            f"'{s.window.boundary}' must be a 1-bit scalar strobe."
                        )
                    if self.reference_model.language != "sv":
                        raise ValueError(
                            f"analysis.scoreboards '{s.name}': a windowed scoreboard "
                            f"needs a SystemVerilog reference model (the accumulate/"
                            f"verdict seams are SV); set reference_model.language: sv."
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
        # M1 — multi-clock / multi-reset validation. A scalar `clock:` with no `resets:`
        # list is single-domain — the checks below run but pass trivially (one clock,
        # the synthesized/absent reset); the legacy tb_top path renders byte-identical.
        clock_names = [c.name for c in self.effective_clocks]
        if len(clock_names) != len(set(clock_names)):
            raise ValueError("clock names must be unique.")
        # M1 mixed-unit — clocks may use different time units; the tb emits one
        # -timescale at the finest unit and scales each period into it. When units are
        # mixed they must be known SI units (so the scaling is defined).
        units = {c.unit for c in self.effective_clocks}
        if len(units) > 1:
            bad = sorted(u for u in units if u not in _UNIT_MAG)
            if bad:
                raise ValueError(
                    f"unknown clock time unit(s) {bad} — to mix units use one of "
                    f"fs/ps/ns/us/ms/s."
                )
        resets = self.effective_resets
        reset_names = [r.name for r in resets]
        if len(reset_names) != len(set(reset_names)):
            raise ValueError("reset names must be unique.")
        clock_set = set(clock_names)
        for r in resets:
            if r.name in clock_set:
                raise ValueError(
                    f"reset '{r.name}' collides with a clock name — clock and reset "
                    f"nets share the tb_top namespace, so they must differ."
                )
            if r.clock is not None and r.clock not in clock_set:
                raise ValueError(
                    f"reset '{r.name}' names clock '{r.clock}', which is not a "
                    f"declared clock ({', '.join(clock_names)})."
                )
        reset_set = set(reset_names)
        for a in self.agents:
            if a.clock is not None and a.clock not in clock_set:
                raise ValueError(
                    f"agent '{a.name}' names clock '{a.clock}', which is not a "
                    f"declared clock ({', '.join(clock_names)})."
                )
            if a.reset is not None and a.reset not in reset_set:
                raise ValueError(
                    f"agent '{a.name}' names reset '{a.reset}', which is not a "
                    f"declared reset ({', '.join(sorted(reset_set)) or 'none'})."
                )
        # The multi-domain tb_top wires clocks/resets as its own top-level nets, so an
        # agent port sharing a clock/reset net name would double-drive it. (Legacy path
        # allows an agent-driven reset port named `dut.reset` — so multi-domain only.)
        multi = bool(self.clocks) or bool(self.resets)
        if multi:
            net_names = clock_set | reset_set
            for a in self.agents:
                for _, p in a.all_ports:
                    if p.name in net_names:
                        raise ValueError(
                            f"agent '{a.name}' port '{p.name}' collides with a "
                            f"clock/reset net of the same name — rename the port "
                            f"or the domain."
                        )
        # The multi-domain tb_top wires per-AGENT interfaces; it does not yet weave the
        # C3 multi-instantiation (`instances`) wiring. Reject the combo (fail-closed).
        if multi and any(a.instances for a in self.agents):
            raise ValueError(
                "multiple clock/reset domains combined with a multi-instantiated agent "
                "(`instances`) is not supported yet — use one clock domain per bench, "
                "or a single instance per agent."
            )
        if multi and self.subenvs:
            raise ValueError(
                "a subsystem (`subenvs`) bench must not declare top-level `clock:`/"
                "`resets:` lists — a composed clocked block carries its own clock/"
                "reset (the subsystem tb_top generates one per clocked leaf)."
            )
        # M1 — per-agent AGENT-DRIVEN reset ports. `reset_port` names one of the agent's
        # OWN input ports; it is the agent-driven (non-external) path, and combining it
        # with M1 clock/reset domain LISTS is a later slice (fail-closed).
        for a in self.agents:
            if a.reset_port is not None:
                if not any(p.name == a.reset_port for p in a.input_ports):
                    raise ValueError(
                        f"agent '{a.name}': reset_port '{a.reset_port}' is not one of "
                        f"its input ports."
                    )
                if self.dut.external_reset:
                    raise ValueError(
                        f"agent '{a.name}': reset_port is an AGENT-DRIVEN reset and "
                        f"cannot be combined with dut.external_reset (external reset "
                        f"is top-generated, not agent-driven)."
                    )
                if multi:
                    raise ValueError(
                        f"agent '{a.name}': reset_port combined with M1 `clock:`/"
                        f"`resets:` lists is not supported yet (single-clock only)."
                    )
            if a.reset_port_active_low is not None and a.reset_port is None:
                raise ValueError(
                    f"agent '{a.name}': reset_port_active_low requires reset_port."
                )
        # A FLAT bench binds EVERY agent's ports to ONE DUT instance, so two agents
        # sharing a port name would double-bind that DUT port (illegal SV). Per-instance
        # (C3 `instances`) and per-leaf (`subenvs`) benches give each a separate DUT and
        # are exempt (and a subenv top has no agents of its own).
        if not self.subenvs and not self.instance_views:
            owner: dict[str, str] = {}
            for a in self.agents:
                for _, p in a.all_ports:
                    if p.name in owner and owner[p.name] != a.name:
                        raise ValueError(
                            f"agents '{owner[p.name]}' and '{a.name}' both have a port "
                            f"'{p.name}' — the flat tb_top binds every agent port to "
                            f"one DUT port, so port names must be unique across agents "
                            f"(give them distinct names, or hand-wire the "
                            f"dut_connections pragma region)."
                        )
                    owner[p.name] = a.name
            # The DUT stub + tb_top thread only the PRIMARY (first) agent's parameters
            # (the module header uses agents[0]'s `#(...)`), so a NON-primary agent's
            # parameters — e.g. a `width_param` port — would reference an undeclared
            # parameter. A parameterized multi-agent flat bench is unmodeled here.
            for a in self.agents[1:]:
                if a.parameters:
                    raise ValueError(
                        f"agent '{a.name}': only the FIRST agent of a flat bench may "
                        f"be parameterized (the DUT stub + tb_top thread just primary "
                        f"agent's parameters) — reorder it first, or use `instances` / "
                        f"`subenvs`."
                    )
        # Which agents actually get a <agent>_cover instance in the env: the
        # listed agents when an analysis block is present, else just the primary.
        # A coverage model on any other agent would compile but never be sampled.
        covered_agents = (
            set(self.analysis.coverage)
            if self.analysis
            else ({self.agents[0].name} if self.agents else set())
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
            port_by_name = agent.coverable_fields
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
                if ag_obj.is_responder and not ag_obj.is_proactive:
                    raise ValueError(
                        f"vsequence '{vs.name}': step targets RESPONDER agent "
                        f"'{step.agent}'. Its sequencer is owned by its forever "
                        f"responder sequence — a second sequence there would clobber "
                        f"the computed responses with this one's items, and the device "
                        f"would answer garbage while the bench reported PASS. (A "
                        f"`proactive: true` hybrid is exempt: its proactive items are "
                        f"meaningful, not garbage.)"
                    )
                valid_seqs = {s.name for s in ag_obj.sequences} | {
                    ag_obj.default_seq_name
                }
                if step.sequence not in valid_seqs:
                    raise ValueError(
                        f"vsequence '{vs.name}': step sequence '{step.sequence}' is "
                        f"not a library sequence of agent '{step.agent}' (nor its "
                        f"default '{ag_obj.name}_sequence')."
                    )
        # A test's single-agent `sequence:` must not target a RESPONDER either — the
        # vseq guard above covered only virtual sequences.
        for t_ in self.tests:
            if t_.sequence is None:
                continue
            resp_ag = agents_by_name.get(t_.sequence.agent)
            if (
                resp_ag is not None
                and resp_ag.is_responder
                and not resp_ag.is_proactive
            ):
                raise ValueError(
                    f"test '{t_.name}': `sequence` targets RESPONDER agent "
                    f"'{t_.sequence.agent}'. Its sequencer is owned by its forever "
                    f"responder sequence — a second sequence there would clobber the "
                    f"computed responses, and the device would answer garbage while "
                    f"the bench reported PASS. (A `proactive: true` hybrid is exempt.)"
                )
        # A test may name an explicit vsequence or the auto-default (<project>_vseq).
        valid_vseqs = vseq_names | ({self.auto_vseq_name} - {None})
        for t in self.tests:
            if t.vseq is not None and t.vseq not in valid_vseqs:
                raise ValueError(
                    f"test '{t.name}': vseq '{t.vseq}' is not a declared vsequence."
                )
        # K0 — the GENERATED DPI-C bridge marshals each primary-agent field as a scalar
        # DPI arg (≤64-bit). That bridge is a convenience for a simple, pure,
        # per-transaction model; a real golden model is usually a LIBRARY and takes the
        # escape hatch instead (see the error text and docs/reference_model_seam.md).
        if self.reference_model.language == "c":
            for _, p in self.agents[0].all_ports:
                if p.bit_width > 64:
                    raise ValueError(
                        f"reference_model.language='c': field '{p.name}' is "
                        f"{p.bit_width} bits, but the GENERATED DPI-C bridge marshals "
                        f"<=64-bit SCALARS by value.\n\n"
                        f"That bridge exists for a SIMPLE, PURE, PER-TRANSACTION model "
                        f"-- one `{self.dut.name}_predict(scalar, scalar, scalar*)`. A "
                        f"REAL golden model is usually a LIBRARY (byte streams, "
                        f"arrays, a handle you step), which does not fit it -- and "
                        f"does not need it.\n\n"
                        f"DO THIS INSTEAD (it works today): keep "
                        f"`reference_model.language: sv`, declare your library's own "
                        f'`import "DPI-C"` (add its package to `project.imports`, or '
                        f"use the tb_pkg `imports` pragma region), and call it from "
                        f"the `prediction_logic` pragma. The predictor is a CLASS, "
                        f"so it can hold state across transactions.\n\n"
                        f"Worked example: examples/hmac/ calls OpenTitan's `cryptoc` C "
                        f"library (open-array byte streams in, an 8-word digest out) "
                        f"exactly that way. See docs/reference_model_seam.md."
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
    def regress_jobs(self) -> list[dict]:
        """R1 — every runnable ``+UVM_TESTNAME`` in this bench, with its seed count.

        The union of the declared ``tests:``, the RAL ``reg_test``, and one test per
        C5 ``csr_tests`` kind. Each entry is ``{name, seeds}``; ``seeds`` falls back
        to ``regress.seeds`` when the test does not override it.

        NB the RAL basic register test's CLASS is the bare ``reg_test`` — only its
        FILE is ``<dut>_reg_test.svh`` (see templates/reg_test.svh.j2). A testlist
        that assumes the ``<dut>_`` prefix here emits an unregistered test name and
        the run dies with a UVM factory error.
        """
        default_seeds = self.regress.seeds if self.regress else 1
        jobs = [{"name": t.name, "seeds": t.seeds or default_seeds} for t in self.tests]
        rm = self.register_model
        if rm is not None:
            if rm.reg_test:
                jobs.append({"name": "reg_test", "seeds": default_seeds})
            for csr in rm.csr_test_specs:
                jobs.append(
                    {
                        "name": f"{self.dut.name}_csr_{csr['kind']}_test",
                        "seeds": default_seeds,
                    }
                )
        return jobs

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
        path = Path(path)
        with open(path) as fh:
            raw = yaml.safe_load(fh)
        # F2' — resolve `agent_refs:` BEFORE validation so a referenced agent is an
        # ordinary agent for every downstream validator (uniqueness, env wiring) — it
        # differs only in is_reference=True, which makes the generator SKIP its source.
        if isinstance(raw, dict) and raw.get("agent_refs"):
            _resolve_agent_refs(raw, path.parent)
        cfg = cls.model_validate(raw)
        # H1 — resolve each child block config relative to this (top) file, then
        # cross-check the composition once all children are loaded.
        if cfg.subenvs:
            base = path.parent
            # A config path composed >=2 times is "shared" → its instances are
            # auto-namespaced (their classes would otherwise collide).
            paths = [(base / s.config).resolve() for s in cfg.subenvs]
            shared = {p for p in paths if paths.count(p) > 1}
            for s, spath in zip(cfg.subenvs, paths):
                child = cls.from_yaml(base / s.config)
                # H1 reuse — namespace this instance's classes (prefix the child's
                # dut/agent/interface/transaction/sequence names) so a config reused
                # more than once does not produce colliding class/file names.
                prefix = s.resolve_prefix(spath in shared)
                cfg.subenv_namespaces[s.name] = prefix
                if prefix:
                    # Recurse over the WHOLE subtree so a reused subsystem's inner
                    # blocks are prefixed too (leaf → degenerates to the flat body).
                    _apply_namespace_prefix(child, prefix)
                # H1 param propagation — broadcast this instance's overrides to every
                # descendant agent that declares the parameter (a leaf reaches only
                # its own agents; a subsystem reaches its grandchildren).
                if s.params:
                    declared = {
                        p.name
                        for a in _all_descendant_agents(child)
                        for p in a.parameters
                    }
                    for k, v in s.params.items():
                        if k not in declared:
                            raise ValueError(
                                f"subenv '{s.name}': params override '{k}' is not a "
                                f"declared parameter of any agent in block "
                                f"'{child.original_dut_name or child.dut.name}' "
                                f"(declared: {sorted(declared)})."
                            )
                        _bake_param(child, k, v)
                cfg.subenv_configs[s.name] = child
            cfg.validate_subenv_composition()
        return cfg

    @property
    def is_vip(self) -> bool:
        """F2' — a VIP-only generation (packages + manifest, no DUT/env/bench)."""
        return self.kind == "vip"

    @property
    def is_selftest(self) -> bool:
        """F2' — a DUT-less bench that exercises the VIP against itself."""
        return self.kind == "selftest"

    @property
    def generated_agents(self) -> list[AgentConfig]:
        """F2' — the agents whose SOURCE this bench emits: all agents minus the ones
        consumed BY REFERENCE (is_reference, wired from an external VIP). Every
        per-agent source loop iterates THIS, not `agents`, so a referenced agent is
        wired (it stays in `agents`) but never regenerated. With no refs the two are
        identical (byte-identical)."""
        return [a for a in self.agents if not a.is_reference]

    @property
    def referenced_agents(self) -> list[AgentConfig]:
        """F2' — the agents consumed by reference (wired, not generated)."""
        return [a for a in self.agents if a.is_reference]

    @property
    def primary_agent(self) -> AgentConfig:
        """The first agent — used as default for scoreboard/coverage wiring."""
        return self.agents[0]

    @property
    def stimulus_agents(self) -> list[AgentConfig]:
        """Active agents the TEST may start a sequence on.

        A responder's sequencer is OWNED by its forever responder sequence. If the test
        also started a stimulus sequence there, both would feed the same driver and the
        random items would clobber the computed responses — a bench that looks like it
        passes while the device answers garbage. So responders are excluded — EXCEPT a
        HYBRID (`proactive: true`), whose proactive items are meaningful (an
        alert-sender raising alerts), not garbage: it serves the DUT AND initiates, and
        UVM arbitrates its responder sequence against the test's proactive one.
        """
        return [a for a in self.active_agents if (not a.is_responder) or a.is_proactive]

    @property
    def stimulus_primary(self) -> AgentConfig | None:
        """The agent a single-agent test starts its sequence on. NOT `agents[0]` — that
        may be a responder, and starting stimulus there would clobber the computed
        responses with random items (the device would answer garbage while the bench
        reported PASS)."""
        return self.stimulus_agents[0] if self.stimulus_agents else None

    @property
    def responder_only(self) -> bool:
        """No TB-initiated stimulus at all: the DUT is the initiator and the reactive
        agent(s) merely serve it (a CPU fetching from a memory model, say)."""
        return bool(self.active_agents) and not self.stimulus_agents

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
        # STIMULUS agents, not active agents: a responder's sequencer is owned by its
        # forever responder sequence, so a vseq must never fire a sequence there.
        if len(self.stimulus_agents) < 2:
            return None
        return f"{self.dut.name}_vseq"

    @property
    def instance_views(self) -> list[InstanceView]:
        """C3 — the per-instantiation views (env/top/scoreboard) for agents that
        declare `instances`; empty when none do (the legacy per-agent wiring is
        used, byte-identical)."""
        views: list[InstanceView] = []
        for a in self.agents:
            if a.count > 1:
                # I-9 — N identical replicas sharing one vectored DUT.
                for i in range(a.count):
                    views.append(
                        InstanceView(a, f"{a.name}_{i}", "", shared=True, index=i)
                    )
            for inst in a.instances:
                views.append(
                    InstanceView(a, inst.name, a.instance_param_args_values(inst))
                )
        return views

    @property
    def shared_dut(self) -> bool:
        """I-9 — the bench replicates an agent with `count` into ONE vectored DUT (as
        opposed to C3 `instances`, which give each instance its own DUT)."""
        return any(a.count > 1 for a in self.agents)

    @property
    def count_agent(self) -> AgentConfig | None:
        """The agent replicated by `count` (I-9), or None."""
        return next((a for a in self.agents if a.count > 1), None)

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
                    VseqStep(agent=a.name, sequence=a.default_seq_name)
                    for a in self.stimulus_agents
                ],
            )
        ]
