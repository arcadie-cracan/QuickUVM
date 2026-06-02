"""
Merger — preserves user-written code inside pragma sections during regeneration.

Pragma format (UVMF-inspired):
    // pragma quickuvm custom <section_name> begin
    ... user code ...
    // pragma quickuvm custom <section_name> end

The marker comment may use ``//`` (SystemVerilog/C) or ``#`` (filelists, Makefiles,
shell), matching UVMF which supports both.

Safety contract (fail-closed, modelled on UVMF's ``regen.py``):
  * Markers are validated before any merge: unbalanced, mismatched, nested or
    duplicate sections raise :class:`MergeError` *before* anything is written.
  * If the existing file holds hand-written code in a section that the freshly
    rendered template no longer emits, that code is *orphaned*.  By default this
    raises :class:`MergeError` ("potential loss of hand edits").  The caller must
    pass ``allow_drop=True`` to proceed past it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Per-section capture (preserves the body bytes exactly for round-tripping).
#   Group 1: the begin marker line (including its trailing newline)
#   Group 2: section name
#   Group 3: body between begin/end
#   Group 4: the end marker
_SECTION_RE = re.compile(
    r"((?://|#) pragma quickuvm custom (\S+) begin\n)"
    r"(.*?)"
    r"((?://|#) pragma quickuvm custom \2 end)",
    re.DOTALL,
)

# Single-marker matcher used for line-by-line structural validation.
_MARKER_RE = re.compile(r"^\s*(?://|#) pragma quickuvm custom (\S+) (begin|end)\s*$")


class MergeError(Exception):
    """Raised when a merge would be unsafe (malformed markers or orphaned code)."""


@dataclass
class MergeResult:
    """Outcome of merging saved user sections into freshly rendered content."""

    text: str
    preserved: list[str] = field(default_factory=list)  # user code carried over
    created: list[str] = field(default_factory=list)  # new sections (no saved code)
    orphaned: list[str] = field(default_factory=list)  # saved code with no new home


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


def validate_markers(content: str) -> list[str]:
    """Return a list of human-readable errors describing malformed pragma markers.

    Detects: a ``begin`` with no matching ``end`` (e.g. a deleted end marker), a
    stray ``end``, a name mismatch between begin/end, nested sections, and a
    section name used more than once in the same file.  An empty list means the
    markers are well-formed.
    """
    errors: list[str] = []
    open_name: str | None = None
    open_line = 0
    seen: set[str] = set()

    for lineno, line in enumerate(content.splitlines(), start=1):
        m = _MARKER_RE.match(line)
        if not m:
            continue
        name, kind = m.group(1), m.group(2)
        if kind == "begin":
            if open_name is not None:
                errors.append(
                    f"line {lineno}: section '{name}' opened inside still-open "
                    f"section '{open_name}' (nested pragmas are not allowed)"
                )
            else:
                open_name, open_line = name, lineno
        else:  # end
            if open_name is None:
                errors.append(
                    f"line {lineno}: 'end' for section '{name}' has no matching 'begin'"
                )
            elif name != open_name:
                errors.append(
                    f"line {lineno}: 'end {name}' does not match open section "
                    f"'{open_name}' (opened line {open_line})"
                )
                open_name = None
            else:
                if name in seen:
                    errors.append(
                        f"line {lineno}: section '{name}' appears more than once "
                        f"in this file (names must be unique per file)"
                    )
                seen.add(name)
                open_name = None

    if open_name is not None:
        errors.append(
            f"section '{open_name}' (opened line {open_line}) has no matching 'end' "
            f"marker — its contents cannot be safely preserved"
        )
    return errors


# ---------------------------------------------------------------------------
# Extraction / injection
# ---------------------------------------------------------------------------


def _all_sections(content: str) -> dict[str, str]:
    """Return {section_name: body} for every pragma block, including empty ones."""
    return {m.group(2): m.group(3) for m in _SECTION_RE.finditer(content)}


def extract_user_sections(content: str) -> dict[str, str]:
    """Return {section_name: body} for pragma blocks whose body is non-empty.

    Empty / whitespace-only sections are ignored (they carry no user code).
    """
    return {n: b for n, b in _all_sections(content).items() if b.strip()}


def inject_user_sections(content: str, sections: dict[str, str]) -> str:
    """Replace pragma region bodies in *content* with saved user *sections*."""
    if not sections:
        return content

    def _replacer(m: re.Match) -> str:
        name = m.group(2)
        if name in sections:
            return m.group(1) + sections[name] + m.group(4)
        return m.group(0)

    return _SECTION_RE.sub(_replacer, content)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge(
    existing_path: Path,
    generated_content: str,
    *,
    allow_drop: bool = False,
) -> MergeResult:
    """Merge saved user sections from *existing_path* into *generated_content*.

    If *existing_path* does not exist, the generated content is returned as-is.

    Raises :class:`MergeError` if the existing file has malformed markers, or if
    it holds hand-written code in a section the new template no longer emits and
    ``allow_drop`` is False.
    """
    if not existing_path.exists():
        return MergeResult(
            text=generated_content,
            created=list(_all_sections(generated_content).keys()),
        )

    existing = existing_path.read_text(encoding="utf-8")

    errors = validate_markers(existing)
    if errors:
        raise MergeError(
            f"Malformed pragma markers in {existing_path}:\n  " + "\n  ".join(errors)
        )

    existing_sections = _all_sections(existing)
    new_sections = _all_sections(generated_content)

    inject: dict[str, str] = {}
    preserved: list[str] = []
    orphaned: list[str] = []

    for name, body in existing_sections.items():
        if not body.strip():
            continue  # nothing to preserve
        if name in new_sections:
            # Only carry over genuine user edits, not an unchanged default body.
            if body != new_sections[name]:
                inject[name] = body
                preserved.append(name)
        else:
            orphaned.append(name)

    created = [n for n in new_sections if n not in existing_sections]

    if orphaned and not allow_drop:
        raise MergeError(
            f"Potential loss of hand edits in {existing_path}:\n  "
            + "\n  ".join(
                f'section "{n}" has no home in the regenerated file' for n in orphaned
            )
            + "\n  Rename/restore the section, or pass allow_drop=True "
            "(CLI: --allow-drop) to proceed. The previous file is backed up."
        )

    text = inject_user_sections(generated_content, inject)
    return MergeResult(
        text=text, preserved=preserved, created=created, orphaned=orphaned
    )


def list_modified_sections(existing_path: Path) -> list[str]:
    """Return names of user sections that contain non-default (user-written) code."""
    if not existing_path.exists():
        return []
    content = existing_path.read_text(encoding="utf-8")
    return list(extract_user_sections(content).keys())


# ---------------------------------------------------------------------------
# Status analysis
# ---------------------------------------------------------------------------


@dataclass
class FileStatus:
    """How an on-disk file relates to what the generator would now produce."""

    marker_errors: list[str] = field(default_factory=list)  # malformed pragmas
    user_modified: list[str] = field(default_factory=list)  # edited fenced sections
    orphaned: list[str] = field(default_factory=list)  # user code with no new home
    structure_changed: bool = False  # non-fenced content differs from a fresh render

    @property
    def clean(self) -> bool:
        return not (
            self.marker_errors
            or self.user_modified
            or self.orphaned
            or self.structure_changed
        )


def _skeleton(content: str) -> str:
    """Return *content* with every fence body blanked, to compare non-user regions."""
    return _SECTION_RE.sub(lambda m: m.group(1) + m.group(4), content)


def analyze(existing_path: Path, generated_content: str) -> FileStatus | None:
    """Classify an existing file against freshly rendered *generated_content*.

    Returns None if the file does not exist yet.  Distinguishes genuine user
    edits (``user_modified``) from code that would be lost (``orphaned``), and
    flags when the generated (non-fenced) regions differ from a fresh render
    (``structure_changed`` — i.e. an out-of-band hand edit or a template change
    that a regen would overwrite).
    """
    if not existing_path.exists():
        return None

    existing = existing_path.read_text(encoding="utf-8")
    marker_errors = validate_markers(existing)
    if marker_errors:
        # Cannot trust section extraction on a malformed file.
        return FileStatus(marker_errors=marker_errors)

    existing_sections = _all_sections(existing)
    new_sections = _all_sections(generated_content)

    user_modified = [
        n
        for n, b in existing_sections.items()
        if b.strip() and n in new_sections and b != new_sections[n]
    ]
    orphaned = [
        n for n, b in existing_sections.items() if b.strip() and n not in new_sections
    ]
    structure_changed = _skeleton(existing) != _skeleton(generated_content)

    return FileStatus(
        user_modified=user_modified,
        orphaned=orphaned,
        structure_changed=structure_changed,
    )
