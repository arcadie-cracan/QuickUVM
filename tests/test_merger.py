"""Tests for the merger module."""

from quick_uvm.merger import extract_user_sections, inject_user_sections, merge
from pathlib import Path
import tempfile


SAMPLE = """\
class foo;
  // pragma quickuvm custom class_item_additional begin
  // pragma quickuvm custom class_item_additional end

  function void bar();
    // pragma quickuvm custom bar_body begin
    // pragma quickuvm custom bar_body end
  endfunction
endclass
"""

SAMPLE_WITH_USER_CODE = """\
class foo;
  // pragma quickuvm custom class_item_additional begin
  int my_var;
  // pragma quickuvm custom class_item_additional end

  function void bar();
    // pragma quickuvm custom bar_body begin
    my_var = 42;
    // pragma quickuvm custom bar_body end
  endfunction
endclass
"""


def test_extract_empty_sections():
    sections = extract_user_sections(SAMPLE)
    assert sections == {}, "Empty sections should not be extracted"


def test_extract_non_empty_sections():
    sections = extract_user_sections(SAMPLE_WITH_USER_CODE)
    assert "class_item_additional" in sections
    assert "bar_body" in sections
    assert "my_var" in sections["class_item_additional"]
    assert "42" in sections["bar_body"]


def test_inject_preserves_user_code():
    sections = extract_user_sections(SAMPLE_WITH_USER_CODE)
    # Inject extracted sections back into the empty template
    result = inject_user_sections(SAMPLE, sections)
    assert "my_var" in result
    assert "my_var = 42" in result


def test_inject_no_sections_is_noop():
    result = inject_user_sections(SAMPLE, {})
    assert result == SAMPLE


def test_merge_non_existent_file(tmp_path):
    dest = tmp_path / "new_file.svh"
    generated = "generated content\n"
    result = merge(dest, generated)
    assert result == generated


def test_merge_preserves_user_sections(tmp_path):
    dest = tmp_path / "existing.svh"
    dest.write_text(SAMPLE_WITH_USER_CODE, encoding="utf-8")
    # Regenerate from clean template
    result = merge(dest, SAMPLE)
    assert "my_var" in result
    assert "my_var = 42" in result


def test_merge_ignores_empty_existing_sections(tmp_path):
    dest = tmp_path / "existing.svh"
    dest.write_text(SAMPLE, encoding="utf-8")
    new_generated = SAMPLE.replace("class foo", "class foo_v2")
    result = merge(dest, new_generated)
    # No user sections to preserve — should get fresh generated content
    assert "foo_v2" in result


def test_round_trip(tmp_path):
    """Full round-trip: generate → user edits → regenerate → user code preserved."""
    dest = tmp_path / "trans.svh"

    # First generation
    dest.write_text(SAMPLE, encoding="utf-8")

    # Simulate user editing
    dest.write_text(SAMPLE_WITH_USER_CODE, encoding="utf-8")

    # Second generation (fresh template, same pragma structure)
    result = merge(dest, SAMPLE)
    assert "my_var" in result
    assert "my_var = 42" in result
    # Structural content from fresh template is preserved
    assert "class foo" in result
    assert "function void bar" in result
