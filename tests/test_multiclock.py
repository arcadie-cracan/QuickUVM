"""M1 — multi-clock / multi-reset. The union `clock:` grammar, per-agent clock/reset
association, the parameterized clkgen, the per-domain tb_top wiring, and the validators.
Single-domain byte-identity is covered by the whole-suite regeneration gate."""

from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

MCLK = Path(__file__).resolve().parents[1] / "examples" / "mclk" / "mclk.yaml"


def _two_clock_yaml(tmp_path, **overrides):
    body = {
        "clocks": "clock:\n  - {name: clk_sys, period: 10}\n  - {name: clk_io, period: 6}\n",
        "resets": (
            "resets:\n  - {name: rst_sys_n, clock: clk_sys}\n"
            "  - {name: rst_io_n, clock: clk_io}\n"
        ),
        "agents": (
            "agents:\n"
            "  - {name: sys, interface: sys_if, sequence_item: sys_item,"
            " clock: clk_sys, reset: rst_sys_n,\n"
            "     ports: {inputs: [{name: sd, width: 8}], outputs: [{name: sq, width: 8}]}}\n"
            "  - {name: io, interface: io_if, sequence_item: io_item,"
            " clock: clk_io, reset: rst_io_n,\n"
            "     ports: {inputs: [{name: id, width: 8}], outputs: [{name: iq, width: 8}]}}\n"
        ),
    }
    body.update(overrides)
    p = tmp_path / "m.yaml"
    p.write_text(
        "project: {name: m}\n"
        "dut: {name: m, reset: rst_sys_n, external_reset: true}\n"
        + body["clocks"]
        + body["resets"]
        + body["agents"]
        + "tests: [{name: t}]\n"
    )
    return p


# ---- model: union grammar + resolvers ---------------------------------------


_AGENT = {
    "name": "a",
    "interface": "a_if",
    "sequence_item": "a_item",
    "ports": {"inputs": [{"name": "din", "width": 8}]},
}


def test_clock_union_scalar_still_single():
    # a scalar `clock:` (today) yields exactly one clock named `clk`.
    cfg = ProjectConfig(
        project={"name": "p"}, dut={"name": "p"}, clock={"period": 12}, agents=[_AGENT]
    )
    assert [c.name for c in cfg.effective_clocks] == ["clk"]
    assert cfg.effective_clocks[0].period == 12


def test_clock_union_list_splits_primary_and_full():
    cfg = ProjectConfig.from_yaml(MCLK)
    assert [(c.name, c.period) for c in cfg.effective_clocks] == [
        ("clk_sys", 10),
        ("clk_io", 6),
    ]
    assert cfg.clock.name == "clk_sys"  # primary = first (legacy single-clock reads)


def test_effective_resets_synthesizes_single_external():
    # no `resets:` but an external dut.reset → one synthesized reset bound to the clock.
    cfg = ProjectConfig(
        project={"name": "p"},
        dut={"name": "p", "reset": "rst_n", "external_reset": True},
        clock={"period": 10},
        agents=[_AGENT],
    )
    er = cfg.effective_resets
    assert [(r.name, r.active_low, r.clock) for r in er] == [("rst_n", True, "clk")]


def test_agent_clock_and_reset_resolution():
    cfg = ProjectConfig.from_yaml(MCLK)
    io = next(a for a in cfg.agents if a.name == "io")
    assert cfg.agent_clock(io).name == "clk_io"
    assert cfg.agent_reset(io).name == "rst_io_n"
    # default (unnamed) resolves to the first clock / its bound reset
    sys = next(a for a in cfg.agents if a.name == "sys")
    assert cfg.agent_clock(sys).name == "clk_sys"


# ---- generated output -------------------------------------------------------


def test_parameterized_clkgen_and_per_domain_tb_top(tmp_path):
    Generator(ProjectConfig.from_yaml(MCLK)).generate_all(tmp_path)
    ck = (tmp_path / "clkgen.sv").read_text()
    assert "module clkgen #(longint PERIOD" in ck
    assert "forever #(PERIOD / 2) clk = ~clk;" in ck
    top = (tmp_path / "tb_top.sv").read_text()
    assert "clkgen #(10) ck_clk_sys (clk_sys);" in top
    assert "clkgen #(6) ck_clk_io (clk_io);" in top
    # per-reset generators, each synced to its own clock, each its own pragma region
    assert "repeat (5) @(posedge clk_sys);" in top
    assert "repeat (5) @(posedge clk_io);" in top
    assert "// pragma quickuvm custom reset_generator_rst_sys_n begin" in top
    assert "// pragma quickuvm custom reset_generator_rst_io_n begin" in top
    # each interface bound to its domain
    assert "sys_if sys_if_inst (.clk(clk_sys), .rst_sys_n(rst_sys_n));" in top
    assert "io_if io_if_inst (.clk(clk_io), .rst_io_n(rst_io_n));" in top


def test_per_agent_interface_skew_and_reset(tmp_path):
    Generator(ProjectConfig.from_yaml(MCLK)).generate_all(tmp_path)
    io_if = (tmp_path / "io_if.sv").read_text()
    # io domain: period 6, 20% → skew 1.2; reset port is rst_io_n
    assert "interface io_if (input clk, input rst_io_n);" in io_if
    assert "output #1.2;" in io_if
    sys_if = (tmp_path / "sys_if.sv").read_text()
    assert "interface sys_if (input clk, input rst_sys_n);" in sys_if
    assert "output #2;" in sys_if


def test_per_agent_driver_monitor_reset_gating(tmp_path):
    Generator(ProjectConfig.from_yaml(MCLK)).generate_all(tmp_path)
    io_drv = (tmp_path / "io_driver.svh").read_text()
    assert "wait (vif.rst_io_n === 1'b1);" in io_drv
    io_mon = (tmp_path / "io_monitor.svh").read_text()
    assert "wait (vif.rst_io_n === 1'b1);" in io_mon
    sys_drv = (tmp_path / "sys_driver.svh").read_text()
    assert "wait (vif.rst_sys_n === 1'b1);" in sys_drv


# ---- validators (fail-closed) -----------------------------------------------


def test_agent_unknown_clock_rejected(tmp_path):
    p = _two_clock_yaml(
        tmp_path,
        agents=(
            "agents:\n"
            "  - {name: sys, interface: sys_if, sequence_item: sys_item,"
            " clock: nope, reset: rst_sys_n,\n"
            "     ports: {inputs: [{name: sd, width: 8}], outputs: [{name: sq, width: 8}]}}\n"
        ),
    )
    with pytest.raises(Exception, match="names clock 'nope'"):
        ProjectConfig.from_yaml(p)


def test_agent_unknown_reset_rejected(tmp_path):
    p = _two_clock_yaml(
        tmp_path,
        agents=(
            "agents:\n"
            "  - {name: sys, interface: sys_if, sequence_item: sys_item,"
            " clock: clk_sys, reset: nope,\n"
            "     ports: {inputs: [{name: sd, width: 8}], outputs: [{name: sq, width: 8}]}}\n"
        ),
    )
    with pytest.raises(Exception, match="names reset 'nope'"):
        ProjectConfig.from_yaml(p)


def test_reset_names_unknown_clock_rejected(tmp_path):
    p = _two_clock_yaml(
        tmp_path,
        resets="resets:\n  - {name: rst_sys_n, clock: ghost}\n  - {name: rst_io_n, clock: clk_io}\n",
    )
    with pytest.raises(Exception, match="reset 'rst_sys_n' names clock 'ghost'"):
        ProjectConfig.from_yaml(p)


def test_reset_clock_name_collision_rejected(tmp_path):
    # a reset whose name equals a clock name (shared tb_top net namespace)
    p = _two_clock_yaml(
        tmp_path,
        resets="resets:\n  - {name: clk_sys, clock: clk_sys}\n  - {name: rst_io_n, clock: clk_io}\n",
    )
    with pytest.raises(Exception, match="collides with a clock name"):
        ProjectConfig.from_yaml(p)


# ---- review-driven regressions ----------------------------------------------


def test_single_clock_explicit_resets_uses_parameterized_multi_path(tmp_path):
    # A scalar clock + an EXPLICIT `resets:` list must take the multi-domain path
    # (parameterized clkgen + reset generator), not the legacy path — else tb_top
    # overrides a paramless clkgen and the reset net is never driven (hang).
    p = tmp_path / "sr.yaml"
    p.write_text(
        "project: {name: sr}\n"
        "dut: {name: sr, reset: rst_n}\n"
        "clock: {name: clk, period: 10}\n"
        "resets:\n  - {name: rst_n, clock: clk}\n"
        "agents:\n"
        "  - {name: a, interface: a_if, sequence_item: a_item, reset: rst_n,\n"
        "     ports: {inputs: [{name: din, width: 8}], outputs: [{name: dout, width: 8}]}}\n"
        "tests: [{name: t}]\n"
    )
    Generator(ProjectConfig.from_yaml(p)).generate_all(tmp_path / "g")
    ck = (tmp_path / "g" / "clkgen.sv").read_text()
    top = (tmp_path / "g" / "tb_top.sv").read_text()
    assert "module clkgen #(longint PERIOD" in ck  # parameterized
    assert "clkgen #(10) ck_clk (clk);" in top
    assert "// pragma quickuvm custom reset_generator_rst_n begin" in top


def test_agent_reset_naming_synthesized_reset_accepted(tmp_path):
    # `agent.reset` may name the single reset synthesized from dut.external_reset
    # (effective_resets), not just an explicit `resets:` entry.
    p = tmp_path / "s.yaml"
    p.write_text(
        "project: {name: s}\n"
        "dut: {name: s, reset: rst_n, external_reset: true}\n"
        "clock: {period: 10}\n"
        "agents:\n"
        "  - {name: a, interface: a_if, sequence_item: a_item, reset: rst_n,\n"
        "     ports: {inputs: [{name: din, width: 8}], outputs: [{name: dout, width: 8}]}}\n"
        "tests: [{name: t}]\n"
    )
    cfg = ProjectConfig.from_yaml(p)  # must not raise
    assert cfg.agent_reset(cfg.agents[0]).name == "rst_n"


def test_mixed_clock_units_scale_to_finest_timescale(tmp_path):
    # M1 mixed-unit: clocks in different units emit ONE -timescale at the finest unit,
    # with each clock's period + drive skew scaled into it.
    p = _two_clock_yaml(
        tmp_path,
        clocks="clock:\n  - {name: clk_sys, period: 10, unit: ns}\n  - {name: clk_io, period: 6, unit: ps}\n",
    )
    cfg = ProjectConfig.from_yaml(p)
    assert cfg.timescale_unit == "ps"
    scaled = {c.name: cfg.clock_period_ts(c) for c in cfg.effective_clocks}
    assert scaled == {"clk_sys": 10_000, "clk_io": 6}  # 10ns -> 10000ps
    Generator(cfg).generate_all(tmp_path / "g")
    assert "-timescale 1ps/1ps" in (tmp_path / "g" / "run.f").read_text()
    top = (tmp_path / "g" / "tb_top.sv").read_text()
    assert "clkgen #(10000) ck_clk_sys (clk_sys);" in top
    assert "clkgen #(6) ck_clk_io (clk_io);" in top


def test_mixed_unit_drive_skew_scaled_into_timescale(tmp_path):
    # the clocking-block output skew is scaled into the -timescale unit too: the slow
    # (10 ns) lane's 20% skew is 2000 ps, the fast (500 ps) lane's is 100 ps.
    p = _two_clock_yaml(
        tmp_path,
        clocks="clock:\n  - {name: clk_sys, period: 10, unit: ns}\n  - {name: clk_io, period: 6, unit: ps}\n",
    )
    Generator(ProjectConfig.from_yaml(p)).generate_all(tmp_path / "g")
    # sys lane 10 ns = 10000 ps, 20% -> 2000
    assert "output #2000;" in (tmp_path / "g" / "sys_if.sv").read_text()
    # io lane 6 ps, 20% -> 1.2
    assert "output #1.2;" in (tmp_path / "g" / "io_if.sv").read_text()


def test_single_unit_multiclock_timescale_unchanged():
    # mclk is 2 clocks but both ns → the timescale unit stays ns, periods unscaled.
    cfg = ProjectConfig.from_yaml(MCLK)
    assert cfg.timescale_unit == "ns"
    assert {c.name: cfg.clock_period_ts(c) for c in cfg.effective_clocks} == {
        "clk_sys": 10,
        "clk_io": 6,
    }


def test_large_scaled_period_and_skew_exact_no_overflow(tmp_path):
    # review regression: a coarse lane (3 ms) scaled to ps overflows int32 (3e9) and
    # its 20% skew (6e8) exceeds %g's 6 sig figs. The clkgen param must be `longint`
    # and both the PERIOD and the drive skew must be EXACT integers (no scientific
    # notation, no rounding).
    p = _two_clock_yaml(
        tmp_path,
        clocks="clock:\n  - {name: clk_a, period: 3, unit: ms}\n  - {name: clk_b, period: 500, unit: ps}\n",
        resets="resets:\n  - {name: rst_sys_n, clock: clk_a}\n  - {name: rst_io_n, clock: clk_b}\n",
        agents=(
            "agents:\n"
            "  - {name: sys, interface: sys_if, sequence_item: sys_item,"
            " clock: clk_a, reset: rst_sys_n,\n"
            "     ports: {inputs: [{name: sd, width: 8}], outputs: [{name: sq, width: 8}]}}\n"
            "  - {name: io, interface: io_if, sequence_item: io_item,"
            " clock: clk_b, reset: rst_io_n,\n"
            "     ports: {inputs: [{name: id, width: 8}], outputs: [{name: iq, width: 8}]}}\n"
        ),
    )
    Generator(ProjectConfig.from_yaml(p)).generate_all(tmp_path / "g")
    ck = (tmp_path / "g" / "clkgen.sv").read_text()
    top = (tmp_path / "g" / "tb_top.sv").read_text()
    sys_if = (tmp_path / "g" / "sys_if.sv").read_text()
    assert "module clkgen #(longint PERIOD" in ck  # 64-bit, no int32 overflow
    assert "clkgen #(3000000000) ck_clk_a (clk_a);" in top  # 3 ms = 3e9 ps, exact
    assert "output #600000000;" in sys_if  # 20% of 3e9, exact integer
    assert "e+" not in sys_if  # never scientific notation


def test_fractional_skew_still_exact(tmp_path):
    # a genuinely sub-unit skew (6 ps @ 20% = 1.2) stays an exact 2-decimal literal.
    p = _two_clock_yaml(
        tmp_path,
        clocks="clock:\n  - {name: clk_sys, period: 10, unit: ns}\n  - {name: clk_io, period: 6, unit: ps}\n",
    )
    Generator(ProjectConfig.from_yaml(p)).generate_all(tmp_path / "g")
    assert "output #1.2;" in (tmp_path / "g" / "io_if.sv").read_text()


def test_unknown_mixed_clock_unit_rejected(tmp_path):
    # any unknown unit is rejected per-clock at the leaf (ClockConfig), so the
    # timescale scaling is always defined — mixed or not.
    p = _two_clock_yaml(
        tmp_path,
        clocks="clock:\n  - {name: clk_sys, period: 10, unit: ns}\n  - {name: clk_io, period: 6, unit: bogus}\n",
    )
    with pytest.raises(Exception, match="unknown unit"):
        ProjectConfig.from_yaml(p)


def test_agent_port_colliding_with_clock_net_rejected(tmp_path):
    # in the multi-domain path a top-level clock/reset net and an agent port cannot
    # share a name (the DUT connection would double-drive it).
    p = _two_clock_yaml(
        tmp_path,
        agents=(
            "agents:\n"
            "  - {name: sys, interface: sys_if, sequence_item: sys_item,"
            " clock: clk_sys, reset: rst_sys_n,\n"
            "     ports: {inputs: [{name: clk_io, width: 1}], outputs: [{name: sq, width: 8}]}}\n"
        ),
    )
    with pytest.raises(Exception, match="collides with a clock/reset net"):
        ProjectConfig.from_yaml(p)


def test_multiclock_config_round_trips_through_model_dump():
    # the union `clock:` field dumps back to a list so a reloaded config keeps all
    # domains (clocks is a derived, excluded field).
    cfg = ProjectConfig.from_yaml(MCLK)
    reloaded = ProjectConfig(**cfg.model_dump())
    assert [c.name for c in reloaded.effective_clocks] == ["clk_sys", "clk_io"]
