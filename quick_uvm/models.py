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

    @model_validator(mode="after")
    def validate_agents(self) -> "ProjectConfig":
        names = [a.name for a in self.agents]
        if len(names) != len(set(names)):
            raise ValueError("Agent names must be unique.")
        if not self.agents:
            raise ValueError("At least one agent must be defined.")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ProjectConfig":
        with open(path, "r") as fh:
            raw = yaml.safe_load(fh)
        return cls.model_validate(raw)

    @property
    def primary_agent(self) -> AgentConfig:
        """The first agent — used as default for scoreboard/coverage wiring."""
        return self.agents[0]
