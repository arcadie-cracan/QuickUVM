"""Byte-identity gate: every committed example regenerates to itself.

QuickUVM ships committed ``examples/<x>/gen/`` trees. Regenerating one from its
``<x>.yaml`` must reproduce it byte-for-byte — that is the project's core
"output must not change unless a feature is used" discipline. This test is the
ONLY automated guard on that invariant against the SHIPPED trees:
``test_regeneration_is_idempotent`` only checks a fresh render is self-consistent
(second pass == first pass), and CI's generated-sv job lints fresh output without
diffing the committed trees. A generator/template change that silently drifts the
examples passes both of those but fails here.

Each example is regenerated in a sandbox that contains its yaml(s) AND a copy of
the committed ``gen/`` — the latter so the in-place merger preserves hand-edited
pragma regions (e.g. fifo wires its two-stream scoreboard through env/test
pragmas). The regenerated tree is then compared, file-set and bytes, to committed.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_REPO = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO / "examples"


def _committed_example_dirs() -> list[Path]:
    """Every ``examples/<x>/`` that ships a committed ``gen/`` (the regen set)."""
    return sorted(
        {p.parent for p in _EXAMPLES.glob("*/gen") if p.is_dir()},
        key=lambda p: p.name,
    )


@pytest.mark.parametrize("example", _committed_example_dirs(), ids=lambda p: p.name)
def test_committed_example_regenerates_byte_identical(example: Path, tmp_path: Path):
    name = example.name
    cfg_file = example / f"{name}.yaml"
    assert cfg_file.exists(), f"{name}: expected sibling config {name}.yaml"

    committed_gen = example / "gen"
    committed_names = {p.name for p in committed_gen.iterdir() if p.is_file()}

    # Sandbox the whole example tree: the top yaml + any sub-block configs (which
    # subenv composition resolves by relative path, sometimes from subdirs like
    # chan/chan.yaml) + a copy of the committed gen/ (so the in-place merger
    # preserves hand-edited pragmas). The heavy sim/ artifacts aren't read by
    # generation, so skip them for speed.
    sandbox = tmp_path / name
    _ignore = shutil.ignore_patterns("sim", "*.bak.*", "__pycache__")
    shutil.copytree(example, sandbox, ignore=_ignore)

    # F2' — a consumer's `agent_refs` point at a VIP manifest in a SIBLING example
    # (e.g. ../f2_iovip/gen/f2_iovip.qvip). Copy each referenced example dir alongside
    # the sandbox so from_yaml resolves the manifest at the same relative path.
    raw = yaml.safe_load(cfg_file.read_text()) or {}
    for ref in raw.get("agent_refs") or []:
        ref_example = (example / ref["manifest"]).resolve().parent.parent
        dest = sandbox.parent / ref_example.name
        if ref_example.is_dir() and not dest.exists():
            shutil.copytree(ref_example, dest, ignore=_ignore)

    cfg = ProjectConfig.from_yaml(sandbox / f"{name}.yaml")
    results = Generator(cfg).generate_all(sandbox / "gen", backup=False)
    generated_names = {Path(path).name for _status, path in results}

    # 1) Same set of files: no new output, no orphaned committed file.
    assert generated_names == committed_names, (
        f"{name}: file-set drift — "
        f"generated-not-committed={sorted(generated_names - committed_names)}, "
        f"committed-not-generated={sorted(committed_names - generated_names)}"
    )

    # 2) Same bytes for every file.
    drift = [
        n
        for n in sorted(committed_names)
        if (sandbox / "gen" / n).read_bytes() != (committed_gen / n).read_bytes()
    ]
    assert not drift, (
        f"{name}: byte drift vs committed gen/ in {drift} — "
        f"regenerate examples/{name}/gen and review the diff."
    )
