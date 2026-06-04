"""Pydantic v2 data models for QuickUVM configuration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

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


class PortConfig(BaseModel):
    name: str
    width: int = 1
    randomize: bool = True  # only meaningful for input ports
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
    # SystemVerilog constraint expression for this field, emitted in a transaction
    # constraint block (e.g. "a != 0", "amt inside {[0:31]}", "a < b").
    constraint: str | None = None

    @model_validator(mode="after")
    def _check_field_type(self) -> PortConfig:
        if self.enum and self.type:
            raise ValueError(
                f"port '{self.name}': set either 'enum' (generate a TB enum) or "
                f"'type' (reference an external type), not both."
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
    def sv_type(self) -> str:
        """The SystemVerilog type for this field's declaration."""
        if self.enum:
            return f"{self.name}_e"
        if self.type:
            return self.type
        return f"bit [{self.width - 1}:0]" if self.width > 1 else "bit"

    @property
    def dpi_sv_type(self) -> str:
        """SV scalar type for this field as a DPI-C argument (by width, K0)."""
        w = self.width
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
        w = self.width
        return (
            "char"
            if w <= 8
            else "short"
            if w <= 16
            else "int"
            if w <= 32
            else "long long"
        )


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
    kind: Literal["random", "incrementing", "directed", "reset", "error"] = "random"
    count: int = 100
    field: str | None = None  # the input field to step — required by 'incrementing'

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
        if self.count < 1:
            raise ValueError(f"sequence '{self.name}': count must be >= 1.")
        return self


class TestSeqSel(BaseModel):
    """A test's selection of a single agent-library sequence to run (S2)."""

    agent: str
    name: str


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


class AgentConfig(BaseModel):
    name: str
    interface: str
    sequence_item: str
    seq_item_style: Literal["manual", "field_macros"] = "manual"
    active: bool = True
    ports: PortMap = Field(default_factory=_default_ports)
    sequences: list[SequenceConfig] = Field(default_factory=list)  # S2 library

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
        for p in self.input_ports:
            if p.constraint and not p.randomize:
                raise ValueError(
                    f"agent '{self.name}': input port '{p.name}' has a constraint but "
                    f"randomize=false (non-rand). Set randomize=true or drop it."
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
                if fld.enum or fld.type:
                    raise ValueError(
                        f"agent '{self.name}': sequence '{s.name}' steps field "
                        f"'{s.field}', which is enum/typed — 'incrementing' needs a "
                        f"plain integral field."
                    )
                if fld.constraint:
                    raise ValueError(
                        f"agent '{self.name}': sequence '{s.name}' steps field "
                        f"'{s.field}', which also has a per-field constraint — "
                        f"stepping and constraining the same field conflict."
                    )
        return self


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
    source: str  # name of the agent whose analysis port feeds this scoreboard


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


class Coverpoint(BaseModel):
    field: str  # must name a port on the covered agent
    bins: list[CoverageBin] = Field(default_factory=list)
    at_least: int | None = None  # per-coverpoint override of cg option.at_least

    @model_validator(mode="after")
    def _check_cp(self) -> Coverpoint:
        if self.at_least is not None and self.at_least < 1:
            raise ValueError(
                f"coverpoint '{self.field}': at_least must be >= 1 (got "
                f"{self.at_least})."
            )
        seen: set[str] = set()
        for b in self.bins:
            if b.name in seen:
                raise ValueError(
                    f"coverpoint '{self.field}': duplicate bin name '{b.name}'."
                )
            seen.add(b.name)
        return self


class CoverageModel(BaseModel):
    """Opt-in functional coverage model for one agent (V1).

    Generates a real covergroup (config-driven coverpoints + bins + crosses) in
    <agent>_cover, replacing the generic auto-bin stub. Sampled on the monitor's
    analysis write (no new plumbing). Black box: bins encode the spec's
    interesting values independently of the DUT's internals.
    """

    agent: str
    coverpoints: list[Coverpoint] = Field(default_factory=list)
    crosses: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_shape(self) -> CoverageModel:
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
        for cr in self.crosses:
            if len(cr) < 2:
                raise ValueError(
                    f"coverage_model for agent '{self.agent}': a cross needs >= 2 "
                    f"fields, got {cr}."
                )
            for f in cr:
                if f not in cp_fields:
                    raise ValueError(
                        f"coverage_model for agent '{self.agent}': cross references "
                        f"'{f}', which is not a declared coverpoint."
                    )
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
    backdoor_root: str | None = None  # absolute HDL path to the regfile instance;
    # set to enable backdoor (model.add_hdl_path)
    reg_test_door: Literal["frontdoor", "backdoor"] = "frontdoor"
    frontdoor: str | None = None  # custom uvm_reg_frontdoor class to generate +
    # install on all registers (protocol body = pragma)

    @model_validator(mode="after")
    def _check_backdoor(self) -> RegisterModelConfig:
        if self.reg_test_door == "backdoor" and not self.backdoor_root:
            raise ValueError(
                "register_model.reg_test_door='backdoor' requires backdoor_root "
                "(the HDL path to the regfile, e.g. 'top.dut_inst.regs_inst')."
            )
        return self


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
        if self.register_model is not None:
            if self.register_model.bus_agent not in {a.name for a in self.agents}:
                raise ValueError(
                    f"register_model.bus_agent references unknown agent "
                    f"'{self.register_model.bus_agent}'."
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
                if not cp.bins and not port.enum and port.width > 1:
                    raise ValueError(
                        f"coverage_model[{cm.agent}]: coverpoint '{cp.field}' "
                        f"({port.width} bits) needs explicit bins (auto-partition is "
                        f"only for enum/1-bit fields)."
                    )
                hi = (1 << port.width) - 1
                for b in cp.bins:
                    for v in b.all_values():
                        if not (0 <= v <= hi):
                            raise ValueError(
                                f"coverage_model[{cm.agent}]: bin '{b.name}' on "
                                f"'{cp.field}' has value {v} outside 0..{hi} "
                                f"({port.width} bits)."
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
                if p.width > 64:
                    raise ValueError(
                        f"reference_model.language='c': field '{p.name}' is "
                        f"{p.width} bits; DPI-C scalar marshaling supports ≤64-bit "
                        f"fields (wider fields are not yet supported)."
                    )
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
