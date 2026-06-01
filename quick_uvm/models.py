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


class AgentConfig(BaseModel):
    name: str
    interface: str
    transaction: str
    trans_style: Literal["manual", "field_macros"] = "manual"
    active: bool = True
    ports: dict[Literal["inputs", "outputs"], list[PortConfig]] = Field(
        default_factory=lambda: {"inputs": [], "outputs": []}
    )

    @property
    def input_ports(self) -> list[PortConfig]:
        return self.ports.get("inputs", [])

    @property
    def output_ports(self) -> list[PortConfig]:
        return self.ports.get("outputs", [])

    @property
    def all_ports(self) -> list[tuple[Literal["input", "output"], PortConfig]]:
        result = []
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


class DutConfig(BaseModel):
    name: str
    clock: str = "clk"
    reset: str = "rst_n"
    reset_active_low: bool = True


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

    package: str                       # external uvm_reg package to import
    block: str                         # uvm_reg_block subclass name
    map: str = "default_map"           # register map name within the block
    bus_agent: str                     # agent whose sequencer drives front-door access
    adapter: str = "reg_adapter"       # generated uvm_reg_adapter class name
    use_predictor: bool = True         # explicit prediction via the bus agent's ap
    reg_test: bool = True              # generate a hw_reset/bit_bash register test


class ProjectMeta(BaseModel):
    name: str
    author: str = ""
    year: int = 2026


class ProjectConfig(BaseModel):
    project: ProjectMeta
    dut: DutConfig
    clock: ClockConfig = Field(default_factory=ClockConfig)
    agents: list[AgentConfig] = Field(default_factory=list)
    tests: list[TestConfig] = Field(default_factory=lambda: [TestConfig(name="test1")])
    analysis: AnalysisConfig | None = None
    register_model: RegisterModelConfig | None = None

    @model_validator(mode="after")
    def validate_agents(self) -> "ProjectConfig":
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
        return self

    @property
    def reg_bus_agent(self) -> "AgentConfig | None":
        """The agent whose sequencer drives front-door register access."""
        if self.register_model is None:
            return None
        return next(
            (a for a in self.agents if a.name == self.register_model.bus_agent), None
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ProjectConfig":
        with open(path, "r") as fh:
            raw = yaml.safe_load(fh)
        return cls.model_validate(raw)

    @property
    def primary_agent(self) -> AgentConfig:
        """The first agent — used as default for scoreboard/coverage wiring."""
        return self.agents[0]
