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


# --- dangling DUT connections -------------------------------------------------

_DUT_PRAGMA_RE = re.compile(
    r"pragma quickuvm custom dut_connections begin(.*?)"
    r"pragma quickuvm custom dut_connections end",
    re.S,
)
# `<type> <inst> (` at the start of a line — an instantiation in the top.
_INSTANCE_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(", re.M)
_CONNECTION_RE = re.compile(r"\.([A-Za-z_]\w*)\s*\(")
# `8'hFF`, `'0`, `4'b1x0z` — sized literals are not names.
_LITERAL_RE = re.compile(r"\d*'[sS]?[bBdDhHoO]?[0-9a-fA-F_xXzZ?]+")
_NAME_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
# Blocks that REFERENCE signals without declaring them.
_CLOCKING_RE = re.compile(r"\bclocking\b.*?\bendclocking\b", re.S)
_MODPORT_RE = re.compile(r"\bmodport\b[^;]*;")
_RANGE_RE = re.compile(r"\[[^\]]*\]")
_NET_KEYWORDS = r"(?:input|output|inout|logic|wire|bit|reg|var|tri\w*)"
# Words that can start a line before `<name> ;` without being a user type.
_NOT_A_NET_TYPE = (
    r"(?:begin|end|else|assign|if|initial|final|always\w*|return|posedge|negedge|"
    r"repeat|wait|forever|fork|join\w*|module|interface|import|typedef|parameter|"
    r"localparam)"
)


def _close_paren(text: str, open_idx: int) -> int:
    """Index just past the `)` closing the `(` at *open_idx*, or -1."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _strip_param_lists(text: str) -> str:
    """Drop every balanced `#( ... )` group.

    A DUT's `#(.W(WIDTH))` is not a list of port connections, and `clkgen #(10)
    ck (clk)` must still read as an instantiation.
    """
    out: list[str] = []
    i = 0
    while True:
        m = re.search(r"#\s*\(", text[i:])
        if not m:
            out.append(text[i:])
            return "".join(out)
        close = _close_paren(text, i + m.end() - 1)
        if close < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i : i + m.start()] + " ")
        i = close


def _declares(text: str, name: str) -> bool:
    """True when *text* (a top or an interface) DECLARES the net/signal *name*.

    Deliberately strict about what counts: a name that only appears in a clocking
    block or a modport (a reference), in another declaration's range or
    initialiser (a use), or as the target of an assignment after `begin` is NOT
    declared — each of those passed a looser first cut of this check.
    """
    decl = _RANGE_RE.sub(
        " ", _MODPORT_RE.sub(" ", _CLOCKING_RE.sub(" ", _strip_noise(text)))
    )
    n = re.escape(name)
    if re.search(rf"\b{_NET_KEYWORDS}\b[^;)=]*\b{n}\b", decl):
        return True
    # A user-typed signal (`pkt_t pkt;`): type and name on ONE line.
    return bool(
        re.search(
            rf"(?:^|[;\n])[ \t]*(?!{_NOT_A_NET_TYPE}\b)[A-Za-z_]\w*(?:::\w+)?"
            rf"[ \t]+{n}\b[ \t]*[;,]",
            decl,
        )
    )


def find_dangling_dut_connections(
    top_text: str, sources: dict[str, str], path: str = "<sv>"
) -> list[str]:
    """Find DUT port connections that refer to a signal nothing declares.

    The defect this exists for — generated from a config that VALIDATED, with
    `generate` exiting 0::

        cmd_if cmd_if_inst (clk);
        ...
        yapp dut_inst (
          ...
          .rst_n(cmd_if_inst.rst_n)  );      // cmd_if has no `rst_n`

    Xcelium rejects it at ELABORATION (``*E,CUVUNF: Hierarchical name component
    lookup failed``); Verible parses it happily, so no linter closes the gap.

    *top_text* is a generated top; *sources* maps a file's basename (``cmd_if.sv``)
    to its text. Inside the ``dut_connections`` pragma, every name a connection
    uses must be declared: a bare net in the top itself, ``<inst>.<signal>`` in
    the interface ``<inst>`` is an instance of. The pragma is user-editable, so
    this is run on the MERGED text and checks what is actually there.

    Returns a list of human-readable violations (empty = clean).
    """
    violations: list[str] = []
    top = _strip_noise(top_text)
    type_of = {
        m.group(2): m.group(1) for m in _INSTANCE_RE.finditer(_strip_param_lists(top))
    }
    # the pragma markers are comments: find them in the RAW text, then strip
    for block in _DUT_PRAGMA_RE.finditer(top_text):
        body = _strip_param_lists(_strip_noise(block.group(1)))
        for conn in _CONNECTION_RE.finditer(body):
            close = _close_paren(body, conn.end() - 1)
            if close < 0:
                continue
            port = conn.group(1)
            expr = body[conn.end() : close - 1].strip()
            for ref in _NAME_RE.findall(_LITERAL_RE.sub(" ", expr)):
                head, _, rest = ref.partition(".")
                if not rest:
                    if not _declares(top, head):
                        violations.append(
                            f"{path}: .{port}({expr}) — net `{head}` is not declared "
                            f"in the top."
                        )
                    continue
                signal = rest.split(".")[0]
                iface = type_of.get(head)
                if iface is None:
                    violations.append(
                        f"{path}: .{port}({expr}) — `{head}` is not an instance of "
                        f"the top."
                    )
                    continue
                src = sources.get(f"{iface}.sv")
                if src is None:
                    # an interface generated elsewhere (a VIP consumed by
                    # reference): nothing to read it from here
                    continue
                if not _declares(src, signal):
                    violations.append(
                        f"{path}: .{port}({expr}) — `{iface}` declares no signal "
                        f"`{signal}`. Xcelium fails to elaborate this (*E,CUVUNF)."
                    )
    return violations


def check_paths(paths: list[Path]) -> list[str]:
    """Run every static check over each file. Returns all violations."""
    out: list[str] = []
    texts = {p.name: p.read_text() for p in paths}
    for p in paths:
        out.extend(find_type_shadowing(texts[p.name], str(p)))
        if "pragma quickuvm custom dut_connections begin" in texts[p.name]:
            out.extend(find_dangling_dut_connections(texts[p.name], texts, str(p)))
    return out
