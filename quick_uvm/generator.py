"""
Generator — orchestrates Jinja2 rendering and output file management.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from .merger import merge
from .models import InstanceView, ProjectConfig, ScoreboardSpec, TestConfig

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------


def _make_jinja_env() -> Environment:
    return Environment(
        loader=PackageLoader("quick_uvm", "templates"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _skew_literal(pct: int, period_ts: int) -> str:
    """The clocking-block drive-skew delay (`pct`% of `period_ts` after posedge) as an
    EXACT literal: an integer when `pct*period_ts` divides 100, else an exact 2-decimal
    fraction. Computed here (not via `%g` in the template) because M1 mixed-unit scaling
    can make the skew large, and `%g` would silently round/scientific-notate it."""
    num = pct * period_ts
    if num % 100 == 0:
        return str(num // 100)
    q, r = divmod(num, 100)
    return f"{q}.{r:02d}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# FileSpec — describes one file to generate
# ---------------------------------------------------------------------------


@dataclass
class FileSpec:
    template: str  # name inside quick_uvm/templates/
    output: str  # filename to write in output_dir
    context: dict  # extra context variables for this file


def _next_backup_path(path: Path) -> Path:
    """Return the first free rolling backup path ``<file>.bak.<N>``.

    Existing backups are never overwritten: ``N`` increments until an unused
    name is found, so the full history of pre-regeneration versions is kept.
    """
    n = 0
    while True:
        candidate = path.with_name(f"{path.name}.bak.{n}")
        if not candidate.exists():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class Generator:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self._env = _make_jinja_env()

    # ------------------------------------------------------------------
    # Build the ordered list of files to generate
    # ------------------------------------------------------------------

    @staticmethod
    def _sb_set_ctx(base_ctx: dict, cfg: ProjectConfig, sb: ScoreboardSpec) -> dict:
        """Per-scoreboard render context for a multi-scoreboard bench: its own class
        prefix (<dut>_<sbname>) plus its source→monitor types and match strategy."""
        by_name = {a.name: a for a in cfg.agents}
        in_agent = by_name[sb.source]
        out_agent = by_name[sb.monitor] if sb.monitor else in_agent
        return {
            **base_ctx,
            "sb_prefix": f"{cfg.dut.name}_{sb.name}",
            "sb_in_item": in_agent.sequence_item + in_agent.param_args_values,
            "sb_out_item": out_agent.sequence_item + out_agent.param_args_values,
            "sb_in_agent": in_agent,
            "sb_out_agent": out_agent,
            "sb_two_stream": sb.monitor is not None,
            "sb_match": sb.match,
            "sb_match_key": sb.match_key,
            "sb_max_latency": sb.max_latency,
            # M1 — the window is measured on the MONITOR (response) lane, so scale by
            # that agent's clock period (== the sole clock for a single-domain bench)
            # and emit the literal in that lane's time unit.
            "sb_max_lat_time": (
                sb.max_latency * cfg.agent_clock(out_agent).period
                if sb.max_latency
                else None
            ),
            "sb_clock_unit": cfg.agent_clock(out_agent).unit,
        }

    @staticmethod
    def _inst_sb_ctx(base_ctx: dict, cfg: ProjectConfig, iv: InstanceView) -> dict:
        """Per-instance scoreboard context (C3 multi-instantiation): a concrete,
        single-stream scoreboard set typed on this instance's transaction
        specialization (io_seq_item#(16)), prefixed <dut>_<instance>."""
        item = iv.agent.sequence_item + iv.pav
        return {
            **base_ctx,
            "sb_prefix": f"{cfg.dut.name}_{iv.name}",
            "sb_in_item": item,
            "sb_out_item": item,
            "sb_in_agent": iv.agent,
            "sb_out_agent": iv.agent,
            "sb_two_stream": False,
            "sb_match": "in_order",
            "sb_match_key": None,
            "sb_max_latency": None,
            "sb_max_lat_time": None,
            "sb_clock_unit": cfg.agent_clock(iv.agent).unit,
        }

    def files_to_generate(self, subenv: bool = False) -> list[FileSpec]:
        cfg = self.config
        # H1 — a subsystem (top) bench composes child block envs; it has no agents
        # of its own, so it takes a dedicated composition path.
        if cfg.subenvs:
            return self._subenv_composition_files()
        base_ctx = {
            "project": cfg.project,
            "dut": cfg.dut,
            "clock": cfg.clock,
            # M1 — every clock/reset domain (single-domain → one element that renders
            # byte-identical to the legacy scalar wiring).
            "clocks": cfg.effective_clocks,
            "resets": cfg.effective_resets,
            # M1 — the multi-domain tb_top/clkgen path is taken iff the user explicitly
            # declared a `clock:` LIST or a `resets:` list; a scalar `clock:` + the
            # legacy external/agent reset stays on the byte-identical single-clock path.
            "multi_domain": bool(cfg.clocks) or bool(cfg.resets),
            # M1 mixed-unit — one -timescale at the finest unit; each clock's period
            # scaled into it. Single-unit → the unit unchanged + periods unchanged.
            "timescale_unit": cfg.timescale_unit,
            "clock_periods_ts": {
                c.name: cfg.clock_period_ts(c) for c in cfg.effective_clocks
            },
            # M1 — per-agent resolved clock net + external reset, keyed by agent name,
            # for the multi-domain tb_top wiring.
            "agent_clocks": {a.name: cfg.agent_clock(a).name for a in cfg.agents},
            "agent_resets": {a.name: cfg.agent_reset(a) for a in cfg.agents},
            "agents": cfg.agents,
            "tests": cfg.tests,
            "analysis": cfg.analysis,
            "register_model": cfg.register_model,
            "reg_bus_agent": cfg.reg_bus_agent,
            "virtual_sequences": cfg.effective_virtual_sequences,
            "auto_vseq": cfg.auto_vseq_name,
            "reference_model": cfg.reference_model,
            "layout": cfg.layout,
            # C3 — multi-instantiation: per-instance views for the env/top/scoreboard.
            # Empty for a bench without `instances` → the legacy per-agent wiring
            # runs unchanged (byte-identical).
            "instances": cfg.instance_views,
            "has_instances": bool(cfg.instance_views),
        }

        # A2 — scoreboard stream types. Single-stream (default): predict(pa) -> pa
        # (sb_in_item == sb_out_item == primary agent, byte-identical). Two-stream:
        # predict(source_item) -> monitor_item; comparator/expected typed on monitor.
        pa = cfg.agents[0]
        two_stream_sb = None
        if cfg.analysis is not None:
            two_stream_sb = next(
                (s for s in cfg.analysis.scoreboards if s.monitor is not None), None
            )
        if two_stream_sb is not None:
            assert two_stream_sb.monitor is not None  # selected via `if s.monitor`
            by_name = {a.name: a for a in cfg.agents}
            sb_in_agent = by_name[two_stream_sb.source]
            sb_out_agent = by_name[two_stream_sb.monitor]
        else:
            sb_in_agent = pa
            sb_out_agent = pa
        # C3: the scoreboard connects to the agent's ap at concrete param values, so
        # its expected/actual type is the parameterized transaction (io_seq_item#(8));
        # param_args_values is empty for a non-parameterized agent → byte-identical.
        base_ctx["sb_in_item"] = (
            sb_in_agent.sequence_item + sb_in_agent.param_args_values
        )
        base_ctx["sb_out_item"] = (
            sb_out_agent.sequence_item + sb_out_agent.param_args_values
        )
        base_ctx["sb_in_agent"] = sb_in_agent
        base_ctx["sb_out_agent"] = sb_out_agent
        base_ctx["sb_two_stream"] = two_stream_sb is not None
        base_ctx["sb_match"] = two_stream_sb.match if two_stream_sb else "in_order"
        base_ctx["sb_match_key"] = two_stream_sb.match_key if two_stream_sb else None
        # Latency window: cycles → sim time via the clock period (the comparator
        # measures $realtime). None unless set on the (out-of-order) scoreboard.
        max_lat = two_stream_sb.max_latency if two_stream_sb else None
        base_ctx["sb_max_latency"] = max_lat
        # M1 — scale on the monitor lane's clock period (the sole clock, single-domain)
        # and emit the literal in that lane's time unit.
        base_ctx["sb_max_lat_time"] = (
            max_lat * cfg.agent_clock(sb_out_agent).period if max_lat else None
        )
        base_ctx["sb_clock_unit"] = cfg.agent_clock(sb_out_agent).unit
        # Multi-transaction-type: with >=2 scoreboards each gets its OWN typed
        # predictor/comparator/scoreboard/reference_model, prefixed <dut>_<sbname>.
        # With <=1 the single set stays <dut>_* (byte-identical).
        sb_multi = cfg.analysis is not None and len(cfg.analysis.scoreboards) >= 2
        base_ctx["sb_multi"] = sb_multi
        base_ctx["sb_prefix"] = cfg.dut.name

        specs: list[FileSpec] = []

        # ---- global files ------------------------------------------------
        # In subenv (composed-child) mode the top provides the clock + real DUTs,
        # so a child emits only its reusable env layer (no clkgen / DUT stub).
        if not subenv:
            specs.append(FileSpec("clkgen.sv.j2", "clkgen.sv", base_ctx))
            specs.append(FileSpec("dut.sv.j2", f"{cfg.dut.name}.sv", base_ctx))

        # ---- per-agent files (interface + TB components) -----------------
        for agent in cfg.agents:
            ctx = {
                **base_ctx,
                "agent": agent,
                "coverage_model": cfg.coverage_model_for(agent.name),
                # M1 — this agent's resolved clock domain + external reset (None if
                # none). For a single-domain bench these equal the global clock / the
                # dut reset, so the agent templates render byte-identical.
                "agent_clock": cfg.agent_clock(agent),
                "agent_reset": cfg.agent_reset(agent),
                # M1 mixed-unit — this agent's exact clocking-block drive skew (a delay
                # in the -timescale unit). Unchanged for a single-unit bench.
                "agent_clock_skew": _skew_literal(
                    cfg.agent_clock(agent).drive_offset_pct,
                    cfg.clock_period_ts(cfg.agent_clock(agent)),
                ),
            }
            specs.append(FileSpec("agent_if.sv.j2", f"{agent.interface}.sv", ctx))
            specs.append(
                FileSpec("agent_trans.svh.j2", f"{agent.sequence_item}.svh", ctx)
            )
            specs.append(FileSpec("agent_config.svh.j2", f"{agent.name}_cfg.svh", ctx))
            specs.append(
                FileSpec("agent_sequencer.svh.j2", f"{agent.name}_sequencer.svh", ctx)
            )
            specs.append(
                FileSpec("agent_driver.svh.j2", f"{agent.name}_driver.svh", ctx)
            )
            specs.append(
                FileSpec("agent_monitor.svh.j2", f"{agent.name}_monitor.svh", ctx)
            )
            specs.append(FileSpec("agent_agent.svh.j2", f"{agent.name}_agent.svh", ctx))
            specs.append(FileSpec("agent_cover.svh.j2", f"{agent.name}_cov.svh", ctx))

        # ---- scoreboard(s) (prefixed by the DUT/block name) --------------
        dut = cfg.dut.name
        # Each scoreboard "set" is a (predictor, comparator, scoreboard) triple typed
        # to one source→monitor pair. With <=1 effective scoreboard the set is named
        # <dut>_* (base_ctx, byte-identical). With >=2, one <dut>_<sbname>_* set per
        # scoreboard, each carrying its own types/match.
        if cfg.instance_views:
            # C3 multi-instantiation: one concrete scoreboard set per instance,
            # <dut>_<instance>_*, typed on that instance's transaction width.
            sb_sets = [
                self._inst_sb_ctx(base_ctx, cfg, iv) for iv in cfg.instance_views
            ]
        elif sb_multi:
            assert cfg.analysis is not None  # sb_multi implies an analysis block
            sb_sets = [
                self._sb_set_ctx(base_ctx, cfg, sb) for sb in cfg.analysis.scoreboards
            ]
        else:
            sb_sets = [base_ctx]
        for sbx in sb_sets:
            p = sbx["sb_prefix"]
            specs.append(FileSpec("sb_predictor.svh.j2", f"{p}_predictor.svh", sbx))
            specs.append(FileSpec("sb_comparator.svh.j2", f"{p}_comparator.svh", sbx))
            specs.append(FileSpec("tb_scoreboard.svh.j2", f"{p}_scoreboard.svh", sbx))

        # ---- environment -------------------------------------------------
        specs.append(FileSpec("env_config.svh.j2", f"{dut}_env_cfg.svh", base_ctx))
        specs.append(FileSpec("env.svh.j2", f"{dut}_env.svh", base_ctx))

        # ---- per-agent sequences -----------------------------------------
        for agent in cfg.agents:
            # Use the first test's num_items as default sequence length;
            # per-test specialisation happens in the test .svh files.
            first_test = cfg.tests[0] if cfg.tests else TestConfig(name="test1")
            ctx = {**base_ctx, "agent": agent, "test": first_test}
            specs.append(
                FileSpec("agent_sequence.svh.j2", f"{agent.name}_seq.svh", ctx)
            )
            # S2 — the per-agent sequence library (one class per declared sequence)
            for seq in agent.sequences:
                seq_ctx = {**base_ctx, "agent": agent, "sequence": seq}
                specs.append(
                    FileSpec("agent_seq_lib.svh.j2", f"{seq.name}.svh", seq_ctx)
                )

        # ---- C2: virtual sequencer + virtual sequences -------------------
        # `effective_virtual_sequences` = the explicit ones, or an auto-default
        # (one base sequence per active agent) for a >=2-active-agent subsystem.
        effective_vseqs = cfg.effective_virtual_sequences
        if effective_vseqs:
            specs.append(
                FileSpec("env_vsqr.svh.j2", f"{dut}_virtual_sequencer.svh", base_ctx)
            )
            specs.append(
                FileSpec("env_vseq_base.svh.j2", f"{dut}_base_vseq.svh", base_ctx)
            )
            for vseq in effective_vseqs:
                vctx = {**base_ctx, "vseq": vseq}
                specs.append(FileSpec("env_vseq.svh.j2", f"{vseq.name}.svh", vctx))

        # ---- tests -------------------------------------------------------
        # A composed child has no test/top of its own — the top bench drives it.
        if not subenv:
            specs.append(FileSpec("test_base.svh.j2", f"{dut}_base_test.svh", base_ctx))
            for test in cfg.tests:
                ctx = {**base_ctx, "test": test}
                specs.append(FileSpec("test.svh.j2", f"{test.name}.svh", ctx))

        # ---- register model (optional, front-door) -----------------------
        if cfg.register_model is not None:
            specs.append(
                FileSpec(
                    "reg_adapter.svh.j2", f"{cfg.register_model.adapter}.svh", base_ctx
                )
            )
            if cfg.register_model.frontdoor:
                specs.append(
                    FileSpec(
                        "reg_frontdoor.svh.j2",
                        f"{cfg.register_model.frontdoor}.svh",
                        base_ctx,
                    )
                )
            if cfg.register_model.reg_test:
                specs.append(
                    FileSpec("reg_test.svh.j2", f"{dut}_reg_test.svh", base_ctx)
                )
            # C5 — one runnable CSR test per selected kind (UVM built-in reg seqs).
            for csr in cfg.register_model.csr_test_specs:
                specs.append(
                    FileSpec(
                        "csr_test.svh.j2",
                        f"{dut}_csr_{csr['kind']}_test.svh",
                        {**base_ctx, "csr": csr},
                    )
                )

        # ---- reference model(s): SV predict() body, or DPI-C bridge + C stub (K0).
        # Multi-scoreboard is two-stream → SV only (one predict per pair). C3 multi-
        # instantiation likewise emits one concrete SV predict per instance width.
        if sb_multi or cfg.instance_views:
            for sbx in sb_sets:
                specs.append(
                    FileSpec(
                        "sb_reference_model.svh.j2",
                        f"{sbx['sb_prefix']}_reference_model.svh",
                        sbx,
                    )
                )
        elif cfg.reference_model.language == "c":
            specs.append(
                FileSpec(
                    "sb_reference_model_dpi.svh.j2",
                    f"{dut}_reference_model.svh",
                    base_ctx,
                )
            )
            specs.append(
                FileSpec(
                    "sb_reference_model.c.j2", f"{dut}_reference_model.c", base_ctx
                )
            )
        else:
            specs.append(
                FileSpec(
                    "sb_reference_model.svh.j2", f"{dut}_reference_model.svh", base_ctx
                )
            )

        # ---- top + package(s) + filelists --------------------------------
        if subenv:
            # Composed child: emit only the reusable env layer — the agent VIP
            # package(s) + the env package. No top/test package, no tb_top, no
            # run.f (the top bench supplies those and composes this env_pkg).
            for agent in cfg.agents:
                actx = {**base_ctx, "agent": agent}
                specs.append(FileSpec("agent_pkg.sv.j2", f"{agent.name}_pkg.sv", actx))
                specs.append(FileSpec("agent_pkg.f.j2", f"{agent.name}_pkg.f", actx))
            specs.append(FileSpec("env_pkg.sv.j2", f"{dut}_env_pkg.sv", base_ctx))
            specs.append(FileSpec("env_pkg.f.j2", f"{dut}_env_pkg.f", base_ctx))
            return specs
        specs.append(FileSpec("top.sv.j2", "tb_top.sv", base_ctx))
        if cfg.layout == "packaged":
            # F2: a standalone <agent>_pkg per agent + a <dut>_env_pkg + a
            # <dut>_test_pkg, each with its own .f filelist.
            for agent in cfg.agents:
                actx = {**base_ctx, "agent": agent}
                specs.append(FileSpec("agent_pkg.sv.j2", f"{agent.name}_pkg.sv", actx))
                specs.append(FileSpec("agent_pkg.f.j2", f"{agent.name}_pkg.f", actx))
            specs.append(FileSpec("env_pkg.sv.j2", f"{dut}_env_pkg.sv", base_ctx))
            specs.append(FileSpec("env_pkg.f.j2", f"{dut}_env_pkg.f", base_ctx))
            specs.append(FileSpec("test_pkg.sv.j2", f"{dut}_test_pkg.sv", base_ctx))
            specs.append(FileSpec("test_pkg.f.j2", f"{dut}_test_pkg.f", base_ctx))
        else:
            specs.append(FileSpec("tb_pkg.sv.j2", f"{dut}_tb_pkg.sv", base_ctx))
            specs.append(FileSpec("pkg.f.j2", "pkg.f", base_ctx))
        specs.append(FileSpec("run.f.j2", "run.f", base_ctx))

        return specs

    @staticmethod
    def _subenv_level_ctx(cfg: ProjectConfig) -> tuple[dict, list[dict]]:
        """Render context for ONE composition level (top or a nested cluster): its
        own subenv views + cross-block scoreboards (resolved to src/monitor)."""
        name = cfg.dut.name
        xsbs = []
        for sb in cfg.subenv_scoreboards:
            sblk, sagent, mblk, magent = cfg.cross_block_sb_endpoints(sb)
            xsbs.append(
                {
                    "name": sb.name,
                    "cls": f"{name}_{sb.name}_scoreboard",
                    "src_handle": sblk,
                    "src_agent": sagent.name,
                    "mon_handle": mblk,
                    "mon_agent": magent.name,
                }
            )
        ctx = {
            "project": cfg.project,
            "dut": cfg.dut,
            "clock": cfg.clock,
            # M1 clocked-subenv — the subsystem tb_top generates a per-leaf clock +
            # reset for every CLOCKED leaf (combinational leaves keep the shared cadence
            # `clk`). `multi_domain` (any clocked leaf) drives clkgen.sv.j2's
            # parameterized branch + the subenv_top clock/reset block; a fully
            # combinational subsystem stays False → byte-identical single-clock output.
            "clocks": cfg.effective_clocks,
            "multi_domain": any(lv.clocked for lv in cfg.leaf_views),
            "clock_periods_ts": {
                c.name: cfg.clock_period_ts(c) for c in cfg.effective_clocks
            },
            # M1 clocked-subenv — the -timescale unit is the clocked leaves' shared unit
            # (or the top's own when none clocked → byte-identical).
            "timescale_unit": cfg.subsystem_timescale_unit,
            "tests": cfg.tests,
            "subenvs": cfg.subenv_views,
            "layout": cfg.layout,
            "connections": cfg.resolved_connections,
            "subenv_scoreboards": xsbs,
            # env_vseq_base.svh.j2 (reused) reads these; a top vseq is virtual-only.
            "virtual_sequences": [],
            "auto_vseq": f"{name}_vseq",
        }
        return ctx, xsbs

    def _subenv_env_classes(self, cfg: ProjectConfig) -> list[FileSpec]:
        """The composition CLASSES for one level: its cross-block scoreboard set +
        env_cfg / env / virtual_sequencer / base_vseq / vseq. Emitted for the top
        AND every nested cluster (a cluster's are included by the top test_pkg)."""
        ctx, _ = self._subenv_level_ctx(cfg)
        name = cfg.dut.name
        specs: list[FileSpec] = []
        for sb in cfg.subenv_scoreboards:
            sblk, sagent, mblk, magent = cfg.cross_block_sb_endpoints(sb)
            p = f"{name}_{sb.name}"
            sbx = {
                **ctx,
                "sb_prefix": p,
                "sb_in_item": sagent.sequence_item + sagent.param_args_values,
                "sb_out_item": magent.sequence_item + magent.param_args_values,
                "sb_in_agent": sagent,
                "sb_out_agent": magent,
                "sb_two_stream": True,
                "sb_match": "in_order",
                "sb_match_key": None,
                "sb_max_latency": None,
                "sb_max_lat_time": None,
                "sb_clock_unit": cfg.clock.unit,
            }
            specs.append(FileSpec("sb_predictor.svh.j2", f"{p}_predictor.svh", sbx))
            specs.append(FileSpec("sb_comparator.svh.j2", f"{p}_comparator.svh", sbx))
            specs.append(FileSpec("tb_scoreboard.svh.j2", f"{p}_scoreboard.svh", sbx))
            specs.append(
                FileSpec("sb_reference_model.svh.j2", f"{p}_reference_model.svh", sbx)
            )
        specs.append(FileSpec("subenv_top_env_cfg.svh.j2", f"{name}_env_cfg.svh", ctx))
        specs.append(FileSpec("subenv_top_env.svh.j2", f"{name}_env.svh", ctx))
        specs.append(
            FileSpec("subenv_top_vsqr.svh.j2", f"{name}_virtual_sequencer.svh", ctx)
        )
        specs.append(FileSpec("env_vseq_base.svh.j2", f"{name}_base_vseq.svh", ctx))
        specs.append(FileSpec("subenv_top_vseq.svh.j2", f"{name}_vseq.svh", ctx))
        return specs

    def _subenv_composition_files(self) -> list[FileSpec]:
        """H1 — a subsystem (top) bench: every LEAF block's reusable env layer, the
        composition classes for the top AND every nested cluster, plus the top-only
        bench layer (base_test / tests / tb_top / test_pkg / clkgen / run.f). Nested
        subsystems compose recursively; a flat single-level top is byte-identical."""
        cfg = self.config
        if not cfg.subenv_views:
            raise ValueError(
                "subenv child configs are not loaded — build the top via "
                "ProjectConfig.from_yaml() so `subenvs` are resolved before "
                "generation."
            )
        specs: list[FileSpec] = []

        # 1. Recursive walk: leaf env-layers + composition classes for every level.
        def walk(c: ProjectConfig) -> None:
            for sv in c.subenv_views:
                if sv.is_subsystem:
                    walk(sv.cfg)  # nested cluster
                else:
                    specs.extend(Generator(sv.cfg).files_to_generate(subenv=True))
            specs.extend(self._subenv_env_classes(c))

        walk(cfg)

        # 2. The top-only bench layer (walks the whole tree via the model helpers).
        top = cfg.dut.name
        ctx, _ = self._subenv_level_ctx(cfg)
        ctx = {
            **ctx,
            # tb_top emits EVERY level's wires (cross-cluster wires are declared at the
            # top; a nested cluster's own wires resolve with its path prefix). Flat
            # single-level → identical to the top's own resolved_connections.
            "connections": cfg.all_resolved_connections,
            "leaf_views": cfg.leaf_views,
            "config_ops": cfg.config_build_ops,
            "composition_levels": cfg.composition_levels,
            "leaf_env_pkgs": cfg.leaf_env_pkgs,
            "leaf_agent_pkgs": cfg.leaf_agent_pkgs,
        }
        specs.append(FileSpec("clkgen.sv.j2", "clkgen.sv", ctx))
        specs.append(
            FileSpec("subenv_top_base_test.svh.j2", f"{top}_base_test.svh", ctx)
        )
        for test in cfg.tests:
            specs.append(
                FileSpec(
                    "subenv_top_test.svh.j2", f"{test.name}.svh", {**ctx, "test": test}
                )
            )
        specs.append(FileSpec("subenv_top.sv.j2", "tb_top.sv", ctx))
        specs.append(FileSpec("subenv_test_pkg.sv.j2", f"{top}_test_pkg.sv", ctx))
        specs.append(FileSpec("subenv_test_pkg.f.j2", f"{top}_test_pkg.f", ctx))
        specs.append(FileSpec("subenv_run.f.j2", "run.f", ctx))
        return specs

    # ------------------------------------------------------------------
    # Render a single template
    # ------------------------------------------------------------------

    def render(self, spec: FileSpec) -> str:
        tpl = self._env.get_template(spec.template)
        return tpl.render(**spec.context)

    # ------------------------------------------------------------------
    # Write (or merge) a single file
    # ------------------------------------------------------------------

    def _write(
        self,
        output_path: Path,
        content: str,
        dry_run: bool = False,
        allow_drop: bool = False,
        backup: bool = True,
    ) -> tuple[str, str]:
        """Write *content* to *output_path*, merging user sections if the
        file already exists.  Returns (status, output_path_str) where
        status is one of 'created', 'updated', 'unchanged'.

        Before overwriting an existing file a rolling ``<file>.bak.<N>`` copy is
        written (unless *backup* is False), keeping every prior version so any
        regen mishap is recoverable.  Raises
        :class:`~quick_uvm.merger.MergeError` if the merge would be unsafe and
        *allow_drop* is False.
        """
        result = merge(output_path, content, allow_drop=allow_drop)
        merged = result.text

        if dry_run:
            return ("dry-run", str(output_path))

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists() and output_path.read_text(encoding="utf-8") == merged:
            return ("unchanged", str(output_path))

        existed = output_path.exists()
        if existed and backup:
            shutil.copy2(output_path, _next_backup_path(output_path))
        output_path.write_text(merged, encoding="utf-8")
        return ("updated" if existed else "created", str(output_path))

    # ------------------------------------------------------------------
    # Generate all files
    # ------------------------------------------------------------------

    def generate_all(
        self,
        output_dir: Path,
        dry_run: bool = False,
        only: str | None = None,
        allow_drop: bool = False,
        backup: bool = True,
    ) -> list[tuple[str, str]]:
        """Render and write every file.  Returns list of (status, path).

        Propagates :class:`~quick_uvm.merger.MergeError` from any file whose
        merge would be unsafe (caller decides how to surface it).
        """
        results: list[tuple[str, str]] = []
        for spec in self.files_to_generate():
            if only and spec.output != only:
                continue
            content = self.render(spec)
            status, path = self._write(
                output_dir / spec.output,
                content,
                dry_run,
                allow_drop=allow_drop,
                backup=backup,
            )
            results.append((status, path))
        return results
