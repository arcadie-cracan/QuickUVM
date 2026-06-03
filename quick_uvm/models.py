"""Pydantic v2 data models for QuickUVM configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


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


PortMap = dict[Literal["inputs", "outputs"], list[PortConfig]]


def _default_ports() -> PortMap:
    return {"inputs": [], "outputs": []}


class AgentConfig(BaseModel):
    name: str
    interface: str
    transaction: str
    trans_style: Literal["manual", "field_macros"] = "manual"
    active: bool = True
    ports: PortMap = Field(default_factory=_default_ports)

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

    @field_validator("name", "interface", "transaction")
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
        return self


class DutConfig(BaseModel):
    name: str
    clock: str = "clk"
    reset: str = "rst_n"
    reset_active_low: bool = True
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

    @field_validator("name")
    @classmethod
    def no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError(f"Test name '{v}' must not contain spaces.")
        return v


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

    @model_validator(mode="after")
    def validate_agents(self) -> ProjectConfig:
        names = [a.name for a in self.agents]
        if len(names) != len(set(names)):
            raise ValueError("Agent names must be unique.")
        if not self.agents:
            raise ValueError("At least one agent must be defined.")
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
        return self

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
