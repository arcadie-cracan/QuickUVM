"""
QuickUVM CLI — entry point: quick-uvm
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from . import __version__
from .generator import Generator
from .merger import MergeError, analyze
from .models import ProjectConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status_icon(status: str) -> str:
    return {
        "created": "[+]",
        "updated": "[~]",
        "unchanged": "[ ]",
        "dry-run": "[?]",
    }.get(status, status)


def _load_config(config: str) -> ProjectConfig:
    try:
        return ProjectConfig.from_yaml(config)
    except FileNotFoundError:
        raise click.ClickException(f"Config file not found: {config}")
    except Exception as exc:
        raise click.ClickException(f"Invalid config: {exc}")


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version")
def main() -> None:
    """QuickUVM — UVM testbench generator (Paradigm Works style).\n
    User-written code inside '// pragma quickuvm custom … begin/end' blocks
    is preserved across regenerations.
    """


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "-c",
    "--config",
    required=True,
    metavar="YAML",
    help="Path to the project config file.",
)
@click.option(
    "-o",
    "--output",
    default=None,
    metavar="DIR",
    help="Output directory (default: value of project.output_dir or ./tb).",
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be written without writing."
)
@click.option(
    "--only",
    multiple=True,
    metavar="FILENAME",
    help="Generate only the specified output filename(s). Repeatable — pass "
    "--only once per file to regenerate one element (see the `manifest` command).",
)
@click.option(
    "--allow-drop",
    is_flag=True,
    help="Proceed even if user code would be lost (orphaned pragma "
    "sections). Default: fail closed.",
)
@click.option(
    "--no-backup",
    is_flag=True,
    help="Do not write <file>.bak copies before overwriting.",
)
def generate(
    config: str,
    output: str | None,
    dry_run: bool,
    only: tuple[str, ...],
    allow_drop: bool,
    no_backup: bool,
) -> None:
    """Generate (or regenerate) the testbench files."""
    cfg = _load_config(config)
    out_dir = Path(output) if output else Path("tb")
    gen = Generator(cfg)

    click.echo(f"QuickUVM  {__version__}  →  {out_dir.resolve()}")
    if dry_run:
        click.echo("  (dry-run mode — no files written)\n")

    # Warn on any --only value that matches no generated file (a renamed element +
    # a stale name would otherwise regenerate NOTHING silently).
    if only:
        gen._output_dir = out_dir
        produced = {spec.output for spec in gen.files_to_generate()}
        for name in only:
            if name not in produced:
                click.echo(
                    f"  [!]  --only '{name}' matches no generated file", err=True
                )

    try:
        results = gen.generate_all(
            out_dir,
            dry_run=dry_run,
            only=only,
            allow_drop=allow_drop,
            backup=not no_backup,
        )
    except MergeError as exc:
        raise click.ClickException(
            f"{exc}\n\nRefusing to overwrite to avoid losing hand-written code. "
            "Fix the markers, or re-run with --allow-drop to proceed."
        )

    for status, path in results:
        click.echo(f"  {_status_icon(status)}  {path}")

    if not dry_run:
        created = sum(1 for s, _ in results if s == "created")
        updated = sum(1 for s, _ in results if s == "updated")
        unchanged = sum(1 for s, _ in results if s == "unchanged")
        click.echo(f"\n  {created} created, {updated} updated, {unchanged} unchanged.")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command("init")
@click.option(
    "-n",
    "--name",
    required=True,
    metavar="NAME",
    help="Project name (used as the TB package prefix).",
)
@click.option(
    "-o",
    "--output",
    default=None,
    metavar="FILE",
    help="Write config to FILE (default: <name>.yaml).",
)
@click.option(
    "--dut",
    "dut_name",
    default=None,
    metavar="MODULE",
    help="DUT module name (default: same as project name).",
)
def init_cmd(name: str, output: str | None, dut_name: str | None) -> None:
    """Scaffold a starter YAML configuration file."""
    dut_name = dut_name or name
    dest = Path(output) if output else Path(f"{name}.yaml")

    starter = {
        "project": {
            "name": name,
            "author": "",
            "year": 2026,
        },
        "dut": {
            "name": dut_name,
            "clock": "clk",
            "reset": "rst_n",
            "reset_active_low": True,
        },
        "clock": {
            "period": 10,
            "unit": "ns",
            "drive_offset_pct": 20,
        },
        "agents": [
            {
                "name": f"{name}_agt",
                "interface": f"{name}_if",
                "sequence_item": f"{name}_seq_item",
                "seq_item_style": "manual",
                "active": True,
                "ports": {
                    "outputs": [
                        {"name": "dout", "width": 16},
                    ],
                    "inputs": [
                        {"name": "din", "width": 16},
                        {"name": "rst_n", "width": 1, "randomize": True},
                    ],
                },
            }
        ],
        "tests": [
            {"name": "test1", "num_items": 100},
        ],
    }

    if dest.exists():
        click.confirm(f"{dest} already exists. Overwrite?", abort=True)

    dest.write_text(yaml.dump(starter, default_flow_style=False, sort_keys=False))
    click.echo(f"Created {dest}")
    click.echo(f"  Edit it, then run:  quick-uvm generate --config {dest}")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@main.command("list")
@click.option(
    "-c",
    "--config",
    required=True,
    metavar="YAML",
    help="Path to the project config file.",
)
@click.option(
    "-o",
    "--output",
    default=None,
    metavar="DIR",
    help="Output directory used to check existence (default: ./tb).",
)
def list_cmd(config: str, output: str | None) -> None:
    """List files that would be generated without writing anything."""
    cfg = _load_config(config)
    out_dir = Path(output) if output else Path("tb")
    gen = Generator(cfg)
    gen._output_dir = out_dir  # F2': relative -F path for referenced VIP filelists
    specs = gen.files_to_generate()

    click.echo(f"{'Template':<40}  {'Output file':<35}  Exists")
    click.echo("-" * 80)
    for spec in specs:
        dest = out_dir / spec.output
        exists = "yes" if dest.exists() else "no "
        click.echo(f"  {spec.template:<38}  {spec.output:<35}  {exists}")


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


@main.command("manifest")
@click.option(
    "-c",
    "--config",
    required=True,
    metavar="YAML",
    help="Path to the project config file.",
)
@click.option(
    "-o",
    "--output",
    default=None,
    metavar="DIR",
    help="Output directory used for the per-file `exists` flags (default: ./tb).",
)
def manifest_cmd(config: str, output: str | None) -> None:
    """Emit a JSON map of config ELEMENT → generated files.

    Groups the would-be-generated files by owning element (`agent:<name>`,
    `scoreboard:<name>`, `test:<name>`, `vseq:<name>`, `register_model`, `probes`,
    `vip`) plus an `aggregate` group (the whole-config files — packages, filelists,
    top, env, clkgen, DUT stub — that must be co-regenerated on any structural
    add/remove/rename). Powers per-item incremental regen (`generate --only …`) and
    QuickUVM Architect's "not generated" decorations.
    """
    cfg = _load_config(config)
    gen = Generator(cfg)
    out_dir = Path(output) if output else None
    click.echo(json.dumps(gen.manifest(output_dir=out_dir), indent=2))


# ---------------------------------------------------------------------------
# add-test
# ---------------------------------------------------------------------------


@main.command("add-test")
@click.option(
    "-c",
    "--config",
    required=True,
    metavar="YAML",
    help="Path to the project config file.",
)
@click.option(
    "-n", "--name", required=True, metavar="NAME", help="Name of the new test class."
)
@click.option(
    "--num-items",
    default=100,
    show_default=True,
    help="Number of sequence items the test will run.",
)
@click.option(
    "-o",
    "--output",
    default=None,
    metavar="DIR",
    help="Output directory (default: ./tb).",
)
def add_test(config: str, name: str, num_items: int, output: str | None) -> None:
    """Add a new test to the project config and regenerate test files."""
    cfg_path = Path(config)
    cfg = _load_config(config)

    if any(t.name == name for t in cfg.tests):
        raise click.ClickException(f"Test '{name}' already exists in config.")

    # Append test entry to raw YAML
    with open(cfg_path) as fh:
        raw = yaml.safe_load(fh)
    raw.setdefault("tests", []).append({"name": name, "num_items": num_items})
    cfg_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))
    click.echo(f"Added test '{name}' to {cfg_path}")

    # Reload and regenerate only the affected files
    cfg = ProjectConfig.from_yaml(cfg_path)
    out_dir = Path(output) if output else Path("tb")
    gen = Generator(cfg)

    results = gen.generate_all(out_dir, only=f"{name}.svh")
    # Also regenerate the package so the new test is included
    results += gen.generate_all(out_dir, only=f"{cfg.dut.name}_tb_pkg.sv")

    for status, path in results:
        click.echo(f"  {_status_icon(status)}  {path}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@main.command("status")
@click.option(
    "-c",
    "--config",
    required=True,
    metavar="YAML",
    help="Path to the project config file.",
)
@click.option(
    "-o",
    "--output",
    default=None,
    metavar="DIR",
    help="Directory to inspect (default: ./tb).",
)
def status(config: str, output: str | None) -> None:
    """Show how on-disk files differ from what a regen would produce.

    Distinguishes preserved user edits from code that would be LOST (orphaned),
    malformed markers, and out-of-band edits to generated regions that a regen
    would overwrite.
    """
    cfg = _load_config(config)
    out_dir = Path(output) if output else Path("tb")
    gen = Generator(cfg)
    gen._output_dir = out_dir  # F2': relative -F path for referenced VIP filelists

    any_findings = False
    for spec in gen.files_to_generate():
        dest = out_dir / spec.output
        if not dest.exists():
            continue
        st = analyze(dest, gen.render(spec))
        if st is None or st.clean:
            continue
        any_findings = True
        notes: list[str] = []
        if st.marker_errors:
            notes.append(
                f"MALFORMED MARKERS ({len(st.marker_errors)}) — run will fail closed"
            )
        if st.orphaned:
            notes.append(f"ORPHANED (will be LOST): {', '.join(st.orphaned)}")
        if st.user_modified:
            notes.append(f"user-modified: {', '.join(st.user_modified)}")
        if st.structure_changed:
            notes.append("out-of-band edits to generated region (regen will overwrite)")
        click.echo(f"  {spec.output}")
        for n in notes:
            click.echo(f"      - {n}")

    if not any_findings:
        click.echo(
            "  Clean: every file matches the generator (no user edits, no drift)."
        )
