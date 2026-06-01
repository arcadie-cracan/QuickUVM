"""Integration tests for the generator."""

from pathlib import Path
import pytest

from quick_uvm.models import ProjectConfig
from quick_uvm.generator import Generator


EXAMPLE_CONFIG = Path(__file__).parent.parent / "examples" / "simple_reg" / "simple_reg.yaml"


@pytest.fixture(scope="module")
def generated_tb(tmp_path_factory):
    """Generate a testbench once and return the output directory."""
    cfg = ProjectConfig.from_yaml(EXAMPLE_CONFIG)
    gen = Generator(cfg)
    out = tmp_path_factory.mktemp("tb")
    gen.generate_all(out)
    return out


EXPECTED_FILES = [
    "CYCLE.sv",
    "clkgen.sv",
    "simple_reg.sv",
    "reg_if.sv",
    "reg_trans.svh",
    "reg_config.svh",
    "env_config.svh",
    "reg_sequencer.svh",
    "reg_driver.svh",
    "reg_monitor.svh",
    "reg_agent.svh",
    "reg_cover.svh",
    "sb_predictor.svh",
    "sb_comparator.svh",
    "tb_scoreboard.svh",
    "env.svh",
    "reg_sequence.svh",
    "test_base.svh",
    "test_rand.svh",
    "sb_calc_exp.svh",
    "top.sv",
    "tb_pkg.sv",
    "pkg.f",
    "run.f",
]


@pytest.mark.parametrize("fname", EXPECTED_FILES)
def test_file_exists(generated_tb, fname):
    assert (generated_tb / fname).exists(), f"Missing file: {fname}"


def test_pragma_markers_in_trans(generated_tb):
    content = (generated_tb / "reg_trans.svh").read_text()
    assert "// pragma quickuvm custom class_item_additional begin" in content
    assert "// pragma quickuvm custom class_item_additional end" in content


def test_pragma_markers_in_driver(generated_tb):
    content = (generated_tb / "reg_driver.svh").read_text()
    assert "// pragma quickuvm custom drive_item_additional begin" in content


def test_pragma_markers_in_calc_exp(generated_tb):
    content = (generated_tb / "sb_calc_exp.svh").read_text()
    assert "// pragma quickuvm custom prediction_logic begin" in content
    assert "// pragma quickuvm custom prediction_logic end" in content


def test_trans_contains_dout(generated_tb):
    content = (generated_tb / "reg_trans.svh").read_text()
    assert "dout" in content


def test_tb_pkg_includes_all_components(generated_tb):
    content = (generated_tb / "tb_pkg.svh").read_text() if (
        generated_tb / "tb_pkg.svh").exists() else (
        generated_tb / "tb_pkg.sv").read_text()
    assert "reg_trans.svh" in content
    assert "reg_agent.svh" in content
    assert "env.svh" in content
    assert "test_rand.svh" in content


def test_env_declares_all_agents(generated_tb):
    content = (generated_tb / "env.svh").read_text()
    assert "reg_agent" in content


def test_scoreboard_uses_primary_transaction(generated_tb):
    content = (generated_tb / "sb_predictor.svh").read_text()
    assert "reg_trans" in content


def test_top_instantiates_interface(generated_tb):
    content = (generated_tb / "top.sv").read_text()
    assert "reg_if" in content


def test_dut_stub_exists_with_reset(generated_tb):
    content = (generated_tb / "simple_reg.sv").read_text()
    assert "rst_n" in content
    assert "pragma quickuvm custom dut_logic" in content


def test_config_load_validation():
    cfg = ProjectConfig.from_yaml(EXAMPLE_CONFIG)
    assert cfg.project.name == "simple_reg_tb"
    assert len(cfg.agents) == 1
    assert cfg.agents[0].name == "reg"
    assert cfg.primary_agent.transaction == "reg_trans"


def test_scoreboard_report_warns_on_zero_vectors(generated_tb):
    """Comparator fails only on real mismatches; 0 vectors -> warning (e.g. a
    backdoor-only register test drives no bus traffic)."""
    c = (generated_tb / "sb_comparator.svh").read_text()
    assert 'if (ERROR_CNT)' in c
    assert '`uvm_error("FAILED"' in c
    assert 'VECT_CNT == 0' in c
    assert '`uvm_warning("NOVEC"' in c
