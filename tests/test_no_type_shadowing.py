"""Static gate: generated SV must never shadow a type it then uses as a scope.

This is the check that stands in for a simulator on hosted CI. It exists because a
real defect shipped: the env's coverage handle was emitted as ``<agent>_cov
<agent>_cov;`` (member name == type name) and then used as ``<agent>_cov::type_id::
create(...)``. Verible accepted it; Xcelium rejected it at COMPILE time
(``*E,NOPBIND: Package <agent>_cov could not be bound``). Verilator accepts it too,
so no free simulator closes this gap — only a targeted static check does.

See ``docs/parity_roadmap.md`` § R1 and ``quick_uvm/svcheck.py``.
"""

from pathlib import Path

import pytest

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig
from quick_uvm.svcheck import find_type_shadowing

_REPO = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO / "examples"


# --- the checker itself -----------------------------------------------------


def test_flags_the_real_bug():
    """The exact shape that shipped and broke Xcelium."""
    sv = """
class alu_env extends uvm_env;
  alu_cov alu_cov;
  function void build_phase(uvm_phase phase);
    alu_cov = alu_cov::type_id::create("alu_cov", this);
  endfunction
endclass
"""
    v = find_type_shadowing(sv)
    assert len(v) == 1, v
    assert "alu_cov" in v[0]


def test_accepts_the_fix():
    """Renaming the handle (the actual fix) clears it."""
    sv = """
class alu_env extends uvm_env;
  alu_cov alu_cov_h;
  function void build_phase(uvm_phase phase);
    alu_cov_h = alu_cov::type_id::create("alu_cov_h", this);
  endfunction
endclass
"""
    assert find_type_shadowing(sv) == []


def test_shadowing_declaration_alone_is_legal():
    """THE load-bearing case.

    ``<type> <same_name>;`` on its own compiles fine — Xcelium only chokes when a
    bare ``<type>::`` follows in the SAME class scope. QuickUVM ships ~43 of these
    benign declarations (``<agent>_cfg <agent>_cfg;`` in every ``*_env_cfg.svh``).
    A naive "member != type" rule would flag them all and force a mass rename of
    every example, breaking byte-identity for zero safety. It must not fire here.
    """
    sv = """
class fifo_env_cfg extends uvm_object;
  wr_cfg wr_cfg;
  rd_cfg rd_cfg;
endclass
"""
    assert find_type_shadowing(sv) == []


def test_use_in_a_different_class_is_legal():
    """The type scope is only shadowed inside the class that declares the member."""
    sv = """
class fifo_env_cfg extends uvm_object;
  wr_cfg wr_cfg;
endclass

class fifo_base_test extends uvm_test;
  function void build_phase(uvm_phase phase);
    env_cfg.wr_cfg = wr_cfg::type_id::create("wr_cfg");
  endfunction
endclass
"""
    assert find_type_shadowing(sv) == []


def test_member_access_is_not_a_type_scope():
    """``foo.bar::`` / ``a_bar::`` must not be mistaken for a bare ``bar::``."""
    sv = """
class c extends uvm_object;
  bar bar;
  function void f();
    x = other_bar::type_id::create("x");
    y = cfg.bar::nope;
  endfunction
endclass
"""
    assert find_type_shadowing(sv) == []


def test_qualified_declaration_still_shadows():
    """A false NEGATIVE here is a shipped bug — this is the only enforced gate.

    `protected foo_cov foo_cov;` shadows exactly as fatally as the bare form, so the
    qualifier must be skipped, not mistaken for the type.
    """
    for qual in ("protected", "local", "static", "rand", "const"):
        sv = f"""
class alu_env extends uvm_env;
  {qual} alu_cov alu_cov;
  function void build_phase(uvm_phase phase);
    alu_cov = alu_cov::type_id::create("alu_cov", this);
  endfunction
endclass
"""
        assert len(find_type_shadowing(sv)) == 1, f"missed a `{qual}` declaration"


def test_parameterized_type_scope_still_shadows():
    """`foo#(8)::type_id::create()` is the same type reference as `foo::`."""
    sv = """
class e extends uvm_env;
  io_cov io_cov;
  function void build_phase(uvm_phase phase);
    io_cov = io_cov#(8)::type_id::create("io_cov", this);
  endfunction
endclass
"""
    assert len(find_type_shadowing(sv)) == 1


def test_type_scope_in_a_comment_is_not_a_violation():
    """A `<type>::` in a comment or a string is not a type reference."""
    sv = """
class fifo_env_cfg extends uvm_object;
  wr_cfg wr_cfg;
  // historical note: this used to read wr_cfg::type_id::create(...)
  string s = "wr_cfg::type_id";
endclass
"""
    assert find_type_shadowing(sv) == []


# --- every generated example ------------------------------------------------


def _example_configs() -> list[Path]:
    return sorted(
        (d / f"{d.name}.yaml")
        for d in _EXAMPLES.iterdir()
        if d.is_dir() and (d / f"{d.name}.yaml").exists()
    )


@pytest.mark.parametrize("cfg_file", _example_configs(), ids=lambda p: p.parent.name)
def test_generated_example_has_no_type_shadowing(cfg_file: Path, tmp_path: Path):
    """No example may generate the fatal shape. Runs on hosted CI, no licence."""
    cfg = ProjectConfig.from_yaml(cfg_file)
    Generator(cfg).generate_all(tmp_path, backup=False)

    violations: list[str] = []
    for sv in sorted(tmp_path.glob("*.sv")) + sorted(tmp_path.glob("*.svh")):
        violations.extend(find_type_shadowing(sv.read_text(), sv.name))

    assert not violations, "\n".join(violations)
