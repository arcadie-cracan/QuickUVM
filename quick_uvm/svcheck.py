"""Static checks over GENERATED SystemVerilog that a linter cannot see.

Verible (the CI lint) is a style/syntax linter: it happily accepts code that a real
simulator rejects at compile time. This module carries the checks that close that
gap for the specific defects QuickUVM can emit, so they are caught on hosted CI
without a simulator licence.

Currently one check — :func:`find_type_shadowing`.
"""

from __future__ import annotations

import re
from pathlib import Path

# `class foo extends bar;` / `virtual class foo;` — the scope opener.
_CLASS_RE = re.compile(r"^\s*(?:virtual\s+)?class\s+(\w+)\b")
_ENDCLASS_RE = re.compile(r"^\s*endclass\b")
# Qualifiers that may precede a member declaration. They must be SKIPPED, not treated
# as the type: `protected foo_cov foo_cov;` shadows just as fatally as the bare form,
# and a checker that misses it is a false negative in the only enforced gate.
_QUALIFIER = r"(?:local|protected|static|automatic|const|rand|randc|var)"
# A member declaration: `[qualifiers] <Type>[#(...)] <name>;`  (a `= init` is allowed).
_DECL_RE = re.compile(
    rf"^\s*(?:{_QUALIFIER}\s+)*([A-Za-z_]\w*)\s*(?:#\s*\([^;]*\))?\s+([A-Za-z_]\w*)\s*"
    r"(?:=[^;]*)?;"
)
# Words that open a declaration but are not a user type.
_NOT_A_TYPE = {
    "return",
    "typedef",
    "import",
    "export",
    "extern",
    "virtual",
    "endclass",
    "begin",
    "end",
    "new",
}
_LINE_COMMENT = re.compile(r"//.*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def _strip_noise(text: str) -> str:
    """Blank out comments and string literals, preserving line structure.

    A `<type>::` inside a comment or a string is not a type reference — scanning raw
    lines for it produces false positives on code the simulator happily accepts.
    """
    text = _BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out = []
    for line in text.splitlines():
        out.append(_LINE_COMMENT.sub("", _STRING.sub('""', line)))
    return "\n".join(out)


def find_type_shadowing(text: str, path: str = "<sv>") -> list[str]:
    """Find members that shadow their own type AND are then used as a type scope.

    The defect this exists for::

        class foo_env extends uvm_env;
          foo_cov foo_cov;                       // member shadows the TYPE `foo_cov`
          ...
          foo_cov = foo_cov::type_id::create();  // *E,NOPBIND at COMPILE time
        endclass

    Xcelium parses the bare ``foo_cov::`` as a *package* reference (the member name
    shadows the type name in that scope) and dies with ``*E,NOPBIND: Package foo_cov
    could not be bound``. Verible and Verilator both accept this file.

    The invariant is deliberately NARROW: a shadowing declaration **alone** is legal
    and QuickUVM ships ~43 of them today (``<agent>_cfg <agent>_cfg;`` in every
    ``*_env_cfg.svh``) — they compile because nothing writes a bare ``<agent>_cfg::``
    in that same class. Flagging every ``member == type`` would fire on all of them
    and force a mass rename for zero safety. Only the *combination* is fatal.

    Returns a list of human-readable violations (empty = clean).
    """
    violations: list[str] = []
    lines = _strip_noise(text).splitlines()

    i = 0
    while i < len(lines):
        m = _CLASS_RE.match(lines[i])
        if not m:
            i += 1
            continue

        # Collect this class's body (to its `endclass`).
        cls_name = m.group(1)
        start = i
        body: list[tuple[int, str]] = []
        i += 1
        while i < len(lines) and not _ENDCLASS_RE.match(lines[i]):
            body.append((i + 1, lines[i]))
            i += 1

        # Members whose name equals their type — the shadowing declarations.
        shadowed: dict[str, int] = {}
        for lineno, line in body:
            d = _DECL_RE.match(line)
            if not d:
                continue
            typ, name = d.group(1), d.group(2)
            if typ in _NOT_A_TYPE or name in _NOT_A_TYPE:
                continue
            if typ == name:
                shadowed[name] = lineno

        # Fatal only if a bare `<type>::` also appears in this same class scope.
        # `<type>#(...)::` (a parameterized specialization) is the same reference and
        # shadows identically, so it must match too.
        for name, decl_line in shadowed.items():
            use_re = re.compile(
                rf"(?<![.\w]){re.escape(name)}\s*(?:#\s*\([^)]*\)\s*)?::"
            )
            for lineno, line in body:
                if lineno == decl_line:
                    continue
                if use_re.search(line):
                    violations.append(
                        f"{path}:{lineno}: `{name}` is declared as a member of class "
                        f"`{cls_name}` at line {decl_line} with the same name as its "
                        f"type, and is used here as a type scope (`{name}::`). The "
                        f"member shadows the type — Xcelium fails to compile this "
                        f"(*E,NOPBIND). Rename the member (e.g. `{name}_h`)."
                    )
                    break

        if i >= len(lines):
            break
        i += 1
        if start == i:  # defensive: never fail to advance
            i += 1

    return violations


def check_paths(paths: list[Path]) -> list[str]:
    """Run every static check over each file. Returns all violations."""
    out: list[str] = []
    for p in paths:
        out.extend(find_type_shadowing(p.read_text(), str(p)))
    return out
