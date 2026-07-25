"""Multi-vendor sim filelists + the coding-assistance core (opt-in `sim:` block).

The portable ``compile.f`` is proven end-to-end against the real simulators on
``examples/reqrsp`` (Cadence + Questa green, VCS wrapper accepted); these tests
pin the generation contract: what is emitted, the portable-core invariants, and
the vendor-specific switches each wrapper must carry.
"""

import pytest
from pydantic import ValidationError

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_BASE = {
    "project": {"name": "s_tb", "author": "a@b.c"},
    "dut": {"name": "s", "clock": "clk", "reset": "", "combinational": True},
    "agents": [
        {
            "name": "io",
            "interface": "io_if",
            "sequence_item": "io_seq_item",
            "ports": {
                "inputs": [{"name": "a", "width": 8, "randomize": True}],
                "outputs": [{"name": "y", "width": 8}],
            },
        }
    ],
    "tests": [{"name": "rand_test"}],
}


def _gen(tmp_path, **over):
    cfg = ProjectConfig.model_validate({**_BASE, **over})
    Generator(cfg).generate_all(tmp_path, backup=False)
    return cfg


def _read(tmp_path, name):
    return (tmp_path / name).read_text()


# --------------------------------------------------------------- opt-in / emission


def test_absent_emits_nothing(tmp_path):
    """No `sim:` => no compile.f, no wrappers => existing benches byte-identical."""
    _gen(tmp_path)
    for f in ("compile.f", "sim_xcelium.sh", "sim_vcs.sh", "sim_questa.sh"):
        assert not (tmp_path / f).exists()


def test_present_emits_core_and_requested_wrappers(tmp_path):
    _gen(tmp_path, sim={"tools": ["xcelium", "vcs", "questa"]})
    assert (tmp_path / "compile.f").exists()
    assert (tmp_path / "sim_xcelium.sh").exists()
    assert (tmp_path / "sim_vcs.sh").exists()
    assert (tmp_path / "sim_questa.sh").exists()


def test_only_requested_vendors_emitted(tmp_path):
    """A subset of tools emits only those wrappers (the core is always there)."""
    _gen(tmp_path, sim={"tools": ["xcelium"]})
    assert (tmp_path / "compile.f").exists()
    assert (tmp_path / "sim_xcelium.sh").exists()
    assert not (tmp_path / "sim_vcs.sh").exists()
    assert not (tmp_path / "sim_questa.sh").exists()


def test_default_tool_is_xcelium(tmp_path):
    """`sim: {}` defaults to the proven Cadence wrapper."""
    _gen(tmp_path, sim={})
    assert (tmp_path / "sim_xcelium.sh").exists()
    assert not (tmp_path / "sim_vcs.sh").exists()


# ----------------------------------------------------- the portable-core invariants


def test_core_is_switch_free(tmp_path):
    """compile.f is the LSP-facing / shared core: sources + incdirs only. The
    tool-specific switches (`-timescale`, `-y`/`+libext`, `-uvm`) must NOT leak in,
    or a language server would choke and the core would stop being portable."""
    _gen(tmp_path, sim={"tools": ["xcelium"]})
    core = _read(tmp_path, "compile.f")
    assert "+incdir+" in core
    assert "-f pkg.f" in core  # the generated tb package sources
    for switch in ("-timescale", "-y ", "+libext", "-uvm", "-access"):
        assert switch not in core, f"portable core leaked a tool switch: {switch}"


def test_core_stub_without_rtl_filelist(tmp_path):
    """No rtl_filelist => the core compiles the generated DUT stub (smoke compile)."""
    _gen(tmp_path, sim={"tools": ["xcelium"]})
    core = _read(tmp_path, "compile.f")
    assert "s.sv" in core  # the <dut>.sv stub
    assert "-f " not in core.replace("-f pkg.f", "")  # no rtl_filelist reference


def test_core_references_rtl_filelist_with_plain_f(tmp_path):
    """With rtl_filelist the core references it via plain `-f` (universal
    cwd-relative) and drops the stub. `-F` is deliberately NOT used — it resolves
    inconsistently across vendors (qrun mixes it), the analysis's top portability
    trap."""
    _gen(tmp_path, sim={"tools": ["xcelium"], "rtl_filelist": "../rtl/dut.f"})
    core = _read(tmp_path, "compile.f")
    assert "-f ../rtl/dut.f" in core
    assert "-F " not in core
    assert "\ns.sv" not in core  # the stub is omitted when real RTL is referenced


# ------------------------------------------------------- the vendor-specific switches


def test_cadence_wrapper_switches(tmp_path):
    _gen(tmp_path, sim={"tools": ["xcelium"]})
    w = _read(tmp_path, "sim_xcelium.sh")
    assert "xrun" in w and "-uvm" in w and "-access +rwc" in w
    assert "-f compile.f" in w


def test_vcs_wrapper_puts_ntb_opts_on_the_command_line(tmp_path):
    """VCS rejects `-ntb_opts uvm` inside a -f file (proven against the tool), so
    the wrapper is a run script with it on the command line, then `./simv`."""
    _gen(tmp_path, sim={"tools": ["vcs"]})
    w = _read(tmp_path, "sim_vcs.sh")
    assert "-ntb_opts uvm" in w
    assert "-f compile.f" in w
    assert "./simv" in w  # the two-step compile -> run


def test_questa_wrapper_uses_qrun(tmp_path):
    """qrun is the single-call flow (auto-creates the work library)."""
    _gen(tmp_path, sim={"tools": ["questa"]})
    w = _read(tmp_path, "sim_questa.sh")
    assert "qrun" in w and "-uvm" in w
    assert "-f compile.f" in w


# ------------------------------------------------------------------- the validators


def test_empty_tools_rejected(tmp_path):
    with pytest.raises(ValidationError, match="at least one vendor"):
        ProjectConfig.model_validate({**_BASE, "sim": {"tools": []}})


def test_duplicate_tools_rejected(tmp_path):
    with pytest.raises(ValidationError, match="duplicate"):
        ProjectConfig.model_validate({**_BASE, "sim": {"tools": ["vcs", "vcs"]}})


def test_unknown_tool_rejected(tmp_path):
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({**_BASE, "sim": {"tools": ["verilator"]}})


def test_blank_rtl_filelist_rejected(tmp_path):
    with pytest.raises(ValidationError, match="non-empty path"):
        ProjectConfig.model_validate({**_BASE, "sim": {"rtl_filelist": "  "}})


# ------------------------------------------------------------------- Bender.yml tail


def test_bender_off_by_default(tmp_path):
    _gen(tmp_path, sim={"tools": ["xcelium"]})
    assert not (tmp_path / "Bender.yml").exists()


def test_bender_emits_manifest_with_tb_and_rtl(tmp_path):
    """`bender: true` emits a Bender.yml listing the TB sources + the RTL read from
    the referenced filelist (Bender needs paths, not a `-f` reference). Validated
    end-to-end on examples/reqrsp: `bender script flist-plus | xrun` runs green."""
    (tmp_path / "dut.f").write_text("// rtl\n../rtl/s_pkg.sv\n../rtl/s.sv\n")
    _gen(tmp_path, sim={"tools": ["xcelium"], "rtl_filelist": "dut.f", "bender": True})
    m = _read(tmp_path, "Bender.yml")
    assert "name: s_tb" in m
    # RTL (from the filelist) then the TB sources QuickUVM owns
    assert "../rtl/s_pkg.sv" in m and "../rtl/s.sv" in m
    assert "s_tb_pkg.sv" in m and "tb_top.sv" in m and "io_if.sv" in m
    assert "include_dirs:" in m


def test_bender_reads_incdirs_from_rtl_filelist(tmp_path):
    """`+incdir+` lines in the RTL filelist carry into the manifest's include_dirs;
    nested `-f`/`-F` and other directives are skipped (documented limitation)."""
    (tmp_path / "dut.f").write_text("+incdir+../rtl/inc\n-f other.f\n../rtl/s.sv\n")
    _gen(tmp_path, sim={"tools": ["xcelium"], "rtl_filelist": "dut.f", "bender": True})
    m = _read(tmp_path, "Bender.yml")
    assert "../rtl/inc" in m  # the +incdir+ was lifted
    assert "../rtl/s.sv" in m
    assert "other.f" not in m  # the nested -f was NOT expanded


def test_bender_stub_without_rtl_filelist(tmp_path):
    """No rtl_filelist => the manifest lists the generated DUT stub."""
    _gen(tmp_path, sim={"tools": ["xcelium"], "bender": True})
    assert "s.sv" in _read(tmp_path, "Bender.yml")


def test_bender_rejected_on_packaged_layout(tmp_path):
    """Flat-only for now: the packaged multi-package source graph is a follow-up."""
    with pytest.raises(ValueError, match="layout: flat"):
        _gen(
            tmp_path,
            layout="packaged",
            sim={"tools": ["xcelium"], "bender": True},
        )


def test_read_filelist_sources_helper(tmp_path):
    """The `.f` flattener: files vs +incdir+ vs skipped comments/directives."""
    from quick_uvm.generator import _read_filelist_sources

    f = tmp_path / "in.f"
    f.write_text("// c\n#c\n+incdir+inc\n-f nested.f\n-F n2.f\na.sv\n  b.sv  \n\n")
    files, incdirs = _read_filelist_sources(f)
    assert files == ["a.sv", "b.sv"]
    assert incdirs == ["inc"]
