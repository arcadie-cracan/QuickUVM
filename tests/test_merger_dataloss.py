"""Phase A0/A1/A2 — fail-closed preservation guarantees.

These tests pin the behaviours that protect user-written code from being lost
during regeneration: orphan detection, marker validation, and backups.
"""

import pytest

from quick_uvm.generator import Generator
from quick_uvm.merger import MergeError, analyze, merge, validate_markers
from quick_uvm.models import ProjectConfig
from pathlib import Path


def _fenced(name: str, body: str = "") -> str:
    return (
        f"// pragma quickuvm custom {name} begin\n"
        f"{body}"
        f"// pragma quickuvm custom {name} end\n"
    )


# ---------------------------------------------------------------------------
# Orphan detection (the critical data-loss case)
# ---------------------------------------------------------------------------

def test_orphaned_user_code_raises_by_default(tmp_path):
    dest = tmp_path / "f.svh"
    dest.write_text("class c;\n" + _fenced("gone", "  int user_field;\n") + "endclass\n")
    # New template no longer emits the 'gone' section.
    new = "class c;\n" + _fenced("present") + "endclass\n"
    with pytest.raises(MergeError, match="gone"):
        merge(dest, new)


def test_orphaned_user_code_proceeds_with_allow_drop(tmp_path):
    dest = tmp_path / "f.svh"
    dest.write_text("class c;\n" + _fenced("gone", "  int user_field;\n") + "endclass\n")
    new = "class c;\n" + _fenced("present") + "endclass\n"
    result = merge(dest, new, allow_drop=True)
    assert "gone" in result.orphaned
    assert "user_field" not in result.text  # dropped, but reported


def test_empty_orphaned_section_is_not_an_error(tmp_path):
    dest = tmp_path / "f.svh"
    dest.write_text("class c;\n" + _fenced("gone") + "endclass\n")  # empty body
    new = "class c;\n" + _fenced("present") + "endclass\n"
    result = merge(dest, new)  # no raise — nothing to lose
    assert result.orphaned == []


# ---------------------------------------------------------------------------
# Marker validation (malformed fences caught before any write)
# ---------------------------------------------------------------------------

def test_missing_end_marker_is_detected():
    content = "class c;\n// pragma quickuvm custom x begin\n  int a;\nendclass\n"
    errors = validate_markers(content)
    assert any("no matching 'end'" in e for e in errors)


def test_missing_end_marker_raises_on_merge(tmp_path):
    dest = tmp_path / "f.svh"
    dest.write_text("// pragma quickuvm custom x begin\n  int a;\n")
    with pytest.raises(MergeError):
        merge(dest, _fenced("x"))


def test_duplicate_section_name_in_file_is_detected():
    content = _fenced("dup", "  int a;\n") + _fenced("dup", "  int b;\n")
    errors = validate_markers(content)
    assert any("more than once" in e for e in errors)


def test_nested_sections_detected():
    content = (
        "// pragma quickuvm custom outer begin\n"
        "// pragma quickuvm custom inner begin\n"
        "// pragma quickuvm custom inner end\n"
        "// pragma quickuvm custom outer end\n"
    )
    errors = validate_markers(content)
    assert any("nested" in e for e in errors)


def test_stray_end_detected():
    content = "// pragma quickuvm custom x end\n"
    errors = validate_markers(content)
    assert any("no matching 'begin'" in e for e in errors)


def test_wellformed_markers_have_no_errors():
    content = _fenced("a", "  int x;\n") + _fenced("b")
    assert validate_markers(content) == []


def test_hash_style_markers_supported():
    content = "# pragma quickuvm custom extra begin\n# pragma quickuvm custom extra end\n"
    assert validate_markers(content) == []


# ---------------------------------------------------------------------------
# Default-stub vs user-code distinction
# ---------------------------------------------------------------------------

def test_unchanged_default_body_flows_through_not_preserved(tmp_path):
    dest = tmp_path / "f.svh"
    default = _fenced("x", "  // default\n")
    dest.write_text(default)
    result = merge(dest, default)  # identical default -> nothing to preserve
    assert result.preserved == []
    assert "// default" in result.text


def test_user_edit_overrides_new_default(tmp_path):
    dest = tmp_path / "f.svh"
    dest.write_text(_fenced("x", "  int user;\n"))
    new = _fenced("x", "  // a different default\n")
    result = merge(dest, new)
    assert "int user;" in result.text
    assert "different default" not in result.text
    assert "x" in result.preserved


# ---------------------------------------------------------------------------
# Backup safety net (generator)
# ---------------------------------------------------------------------------

EXAMPLE_CONFIG = Path(__file__).parent.parent / "examples" / "simple_reg" / "simple_reg.yaml"


def test_backup_written_and_user_code_preserved_on_regen(tmp_path):
    cfg = ProjectConfig.from_yaml(EXAMPLE_CONFIG)
    gen = Generator(cfg)
    gen.generate_all(tmp_path)

    target = tmp_path / "reg_trans.svh"
    original = target.read_text()
    # User edits a fenced section (should survive) AND an out-of-band region
    # (should be reverted on regen — which is what forces the rewrite + backup).
    edited = original.replace(
        "// pragma quickuvm custom class_item_additional begin\n",
        "// pragma quickuvm custom class_item_additional begin\n  int my_extra;\n",
        1,
    ) + "// out-of-band edit\n"
    target.write_text(edited)

    gen.generate_all(tmp_path)  # regenerate

    bak = tmp_path / "reg_trans.svh.bak.0"
    assert bak.exists(), "expected a .bak.0 backup of the pre-regen file"
    assert bak.read_text() == edited                 # backup is the pre-regen content
    new = target.read_text()
    assert "my_extra" in new                          # fenced user code preserved
    assert "// out-of-band edit" not in new           # non-fenced edit reverted


def test_backups_roll_and_never_overwrite(tmp_path):
    cfg = ProjectConfig.from_yaml(EXAMPLE_CONFIG)
    gen = Generator(cfg)
    gen.generate_all(tmp_path)
    target = tmp_path / "reg_trans.svh"

    # Two distinct out-of-band edits, each followed by a regen that rewrites.
    target.write_text(target.read_text() + "// edit ONE\n")
    gen.generate_all(tmp_path)
    target.write_text(target.read_text() + "// edit TWO\n")
    gen.generate_all(tmp_path)

    bak0 = tmp_path / "reg_trans.svh.bak.0"
    bak1 = tmp_path / "reg_trans.svh.bak.1"
    assert bak0.exists() and bak1.exists()
    # bak.0 is the oldest (never overwritten); bak.1 is the more recent.
    assert "// edit ONE" in bak0.read_text() and "// edit TWO" not in bak0.read_text()
    assert "// edit TWO" in bak1.read_text()


# ---------------------------------------------------------------------------
# Status analysis (analyze)
# ---------------------------------------------------------------------------

def test_analyze_clean_when_untouched(tmp_path):
    f = tmp_path / "f.svh"
    content = "class c;\n" + _fenced("x", "  // default\n") + "endclass\n"
    f.write_text(content)
    st = analyze(f, content)  # identical to fresh render
    assert st is not None and st.clean


def test_analyze_flags_user_modified(tmp_path):
    f = tmp_path / "f.svh"
    f.write_text("class c;\n" + _fenced("x", "  int user;\n") + "endclass\n")
    fresh = "class c;\n" + _fenced("x") + "endclass\n"
    st = analyze(f, fresh)
    assert st.user_modified == ["x"]
    assert st.orphaned == []


def test_analyze_flags_orphaned(tmp_path):
    f = tmp_path / "f.svh"
    f.write_text("class c;\n" + _fenced("gone", "  int user;\n") + "endclass\n")
    fresh = "class c;\n" + _fenced("here") + "endclass\n"
    st = analyze(f, fresh)
    assert "gone" in st.orphaned


def test_analyze_flags_out_of_band_edit(tmp_path):
    f = tmp_path / "f.svh"
    fresh = "class c;\n  int generated;\n" + _fenced("x") + "endclass\n"
    f.write_text(fresh.replace("int generated;", "int generated; // hand edit"))
    st = analyze(f, fresh)
    assert st.structure_changed


def test_analyze_reports_marker_errors(tmp_path):
    f = tmp_path / "f.svh"
    f.write_text("// pragma quickuvm custom x begin\n  int a;\n")  # no end
    st = analyze(f, _fenced("x"))
    assert st.marker_errors


def test_no_backup_flag_suppresses_backup(tmp_path):
    cfg = ProjectConfig.from_yaml(EXAMPLE_CONFIG)
    gen = Generator(cfg)
    gen.generate_all(tmp_path)
    target = tmp_path / "reg_trans.svh"
    target.write_text(target.read_text() + "\n// touch\n")
    gen.generate_all(tmp_path, backup=False)
    assert not list(tmp_path.glob("reg_trans.svh.bak.*"))
