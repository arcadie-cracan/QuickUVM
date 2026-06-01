"""
QuickUVM CLI — entry point: quick-uvm
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from . import __version__
from .generator import Generator
from .merger import list_modified_sections
from .models import AgentConfig, PortConfig, ProjectConfig, TestConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_icon(status: str) -> str:
    return {"created": "[+]", "updated": "[~]", "unchanged": "[ ]", "dry-run": "[?]"}.get(
        status, status
    )


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
@click.option("-c", "--config", required=True, metavar="YAML",
              help="Path to the project config file.")
@click.option("-o", "--output", default=None, metavar="DIR",
              help="Output directory (default: value of project.output_dir or ./tb).")
@click.option("--dry-run", is_flag=True,
              help="Show what would be written without writing.")
@click.option("--only", default=None, metavar="FILENAME",
              help="Generate only the specified output filename.")
def generate(config: str, output: str | None, dry_run: bool, only: str | None) -> None:
    """Generate (or regenerate) the testbench files."""
    cfg = _load_config(config)
    out_dir = Path(output) if output else Path("tb")
    gen = Generator(cfg)

    click.echo(f"QuickUVM  {__version__}  →  {out_dir.resolve()}")
    if dry_run:
        click.echo("  (dry-run mode — no files written)\n")

    results = gen.generate_all(out_dir, dry_run=dry_run, only=only)

    for status, path in results:
        click.echo(f"  {_status_icon(status)}  {path}")

    if not dry_run:
        created  = sum(1 for s, _ in results if s == "created")
        updated  = sum(1 for s, _ in results if s == "updated")
        unchanged= sum(1 for s, _ in results if s == "unchanged")
        click.echo(
            f"\n  {created} created, {updated} updated, {unchanged} unchanged."
        )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command("init")
@click.option("-n", "--name", required=True, metavar="NAME",
              help="Project name (used as the TB package prefix).")
@click.option("-o", "--output", default=None, metavar="FILE",
              help="Write config to FILE (default: <name>.yaml).")
@click.option("--dut", "dut_name", default=None, metavar="MODULE",
              help="DUT module name (default: same as project name).")
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
                "transaction": f"{name}_trans",
                "trans_style": "manual",
                "active": True,
                "ports": {
                    "outputs": [
                        {"name": "dout", "width": 16},
                    ],
                    "inputs": [
                        {"name": "din",   "width": 16},
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
@click.option("-c", "--config", required=True, metavar="YAML",
              help="Path to the project config file.")
@click.option("-o", "--output", default=None, metavar="DIR",
              help="Output directory used to check existence (default: ./tb).")
def list_cmd(config: str, output: str | None) -> None:
    """List files that would be generated without writing anything."""
    cfg = _load_config(config)
    out_dir = Path(output) if output else Path("tb")
    gen = Generator(cfg)
    specs = gen.files_to_generate()

    click.echo(f"{'Template':<40}  {'Output file':<35}  Exists")
    click.echo("-" * 80)
    for spec in specs:
        dest = out_dir / spec.output
        exists = "yes" if dest.exists() else "no "
        click.echo(f"  {spec.template:<38}  {spec.output:<35}  {exists}")


# ---------------------------------------------------------------------------
# add-test
# ---------------------------------------------------------------------------

@main.command("add-test")
@click.option("-c", "--config", required=True, metavar="YAML",
              help="Path to the project config file.")
@click.option("-n", "--name", required=True, metavar="NAME",
              help="Name of the new test class.")
@click.option("--num-items", default=100, show_default=True,
              help="Number of sequence items the test will run.")
@click.option("-o", "--output", default=None, metavar="DIR",
              help="Output directory (default: ./tb).")
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
    # Also regenerate tb_pkg.sv so the new test is included
    results += gen.generate_all(out_dir, only="tb_pkg.sv")

    for status, path in results:
        click.echo(f"  {_status_icon(status)}  {path}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command("status")
@click.option("-c", "--config", required=True, metavar="YAML",
              help="Path to the project config file.")
@click.option("-o", "--output", default=None, metavar="DIR",
              help="Directory to inspect (default: ./tb).")
def status(config: str, output: str | None) -> None:
    """Show which user code sections have been modified."""
    cfg = _load_config(config)
    out_dir = Path(output) if output else Path("tb")
    gen = Generator(cfg)
    specs = gen.files_to_generate()

    any_modified = False
    click.echo(f"{'File':<35}  {'Modified sections'}")
    click.echo("-" * 72)
    for spec in specs:
        dest = out_dir / spec.output
        modified = list_modified_sections(dest)
        if modified:
            any_modified = True
            click.echo(f"  {spec.output:<33}  {', '.join(modified)}")

    if not any_modified:
        click.echo("  No modified user sections found.")
