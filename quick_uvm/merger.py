"""
Merger — preserves user-written code inside pragma sections during regeneration.

Pragma format (UVMF-inspired):
    // pragma quickuvm custom <section_name> begin
    ... user code ...
    // pragma quickuvm custom <section_name> end
"""

from __future__ import annotations

import re
from pathlib import Path

# Matches a single named user code section (including its delimiters).
# Group 1: section name
# Group 2: content between begin/end (may be empty or whitespace only)
_SECTION_RE = re.compile(
    r"(// pragma quickuvm custom (\S+) begin\n)"
    r"(.*?)"
    r"(// pragma quickuvm custom \2 end)",
    re.DOTALL,
)


def extract_user_sections(content: str) -> dict[str, str]:
    """Return {section_name: body} for every pragma block found in *content*.

    Only sections whose body is non-empty (has at least one non-whitespace
    character) are returned; empty/default sections are ignored.
    """
    sections: dict[str, str] = {}
    for m in _SECTION_RE.finditer(content):
        name = m.group(2)
        body = m.group(3)
        if body.strip():
            sections[name] = body
    return sections


def inject_user_sections(content: str, sections: dict[str, str]) -> str:
    """Replace empty pragma regions in *content* with saved user *sections*."""
    if not sections:
        return content

    def _replacer(m: re.Match) -> str:
        name = m.group(2)
        if name in sections:
            return m.group(1) + sections[name] + m.group(4)
        return m.group(0)

    return _SECTION_RE.sub(_replacer, content)


def merge(existing_path: Path, generated_content: str) -> str:
    """Read *existing_path*, extract non-empty user sections, inject them into
    *generated_content* and return the merged string.

    If *existing_path* does not exist the generated content is returned as-is.
    """
    if not existing_path.exists():
        return generated_content

    existing = existing_path.read_text(encoding="utf-8")
    user_sections = extract_user_sections(existing)
    if not user_sections:
        return generated_content

    return inject_user_sections(generated_content, user_sections)


def list_modified_sections(existing_path: Path) -> list[str]:
    """Return names of user sections that contain non-default (user-written) code."""
    if not existing_path.exists():
        return []
    content = existing_path.read_text(encoding="utf-8")
    return list(extract_user_sections(content).keys())
