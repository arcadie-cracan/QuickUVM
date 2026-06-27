"""
Generator — orchestrates Jinja2 rendering and output file management.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from .merger import merge
from .models import ProjectConfig, TestConfig

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

    def files_to_generate(self) -> list[FileSpec]:
        cfg = self.config
        base_ctx = {
            "project": cfg.project,
            "dut": cfg.dut,
            "clock": cfg.clock,
            "agents": cfg.agents,
            "tests": cfg.tests,
            "analysis": cfg.analysis,
            "register_model": cfg.register_model,
            "reg_bus_agent": cfg.reg_bus_agent,
            "virtual_sequences": cfg.effective_virtual_sequences,
            "auto_vseq": cfg.auto_vseq_name,
            "reference_model": cfg.reference_model,
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
        base_ctx["sb_in_item"] = sb_in_agent.sequence_item
        base_ctx["sb_out_item"] = sb_out_agent.sequence_item
        base_ctx["sb_in_agent"] = sb_in_agent
        base_ctx["sb_out_agent"] = sb_out_agent
        base_ctx["sb_two_stream"] = two_stream_sb is not None

        specs: list[FileSpec] = []

        # ---- global files ------------------------------------------------
        specs.append(FileSpec("clkgen.sv.j2", "clkgen.sv", base_ctx))
        specs.append(FileSpec("dut.sv.j2", f"{cfg.dut.name}.sv", base_ctx))

        # ---- per-agent files (interface + TB components) -----------------
        for agent in cfg.agents:
            ctx = {
                **base_ctx,
                "agent": agent,
                "coverage_model": cfg.coverage_model_for(agent.name),
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

        # ---- scoreboard (prefixed by the DUT/block name) -----------------
        dut = cfg.dut.name
        specs.append(FileSpec("sb_predictor.svh.j2", f"{dut}_predictor.svh", base_ctx))
        specs.append(
            FileSpec("sb_comparator.svh.j2", f"{dut}_comparator.svh", base_ctx)
        )
        specs.append(
            FileSpec("tb_scoreboard.svh.j2", f"{dut}_scoreboard.svh", base_ctx)
        )

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

        # ---- reference model: SV predict() body, or DPI-C bridge + C stub (K0)
        if cfg.reference_model.language == "c":
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

        # ---- top + package + filelists -----------------------------------
        specs.append(FileSpec("top.sv.j2", "tb_top.sv", base_ctx))
        specs.append(FileSpec("tb_pkg.sv.j2", f"{dut}_tb_pkg.sv", base_ctx))
        specs.append(FileSpec("pkg.f.j2", "pkg.f", base_ctx))
        specs.append(FileSpec("run.f.j2", "run.f", base_ctx))

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
