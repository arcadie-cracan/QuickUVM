"""An unfilled prediction seam must not be able to pass.

`predict()` builds `extr` as a COPY of the observed transaction and hands the user a pragma
in which to overwrite the output fields with a MODEL of the DUT. Leave that seam as the
generated stub and expected == actual for every field — the scoreboard reports "N Ran /
N Passed" against a DUT it never modelled.

That is a green bench measuring nothing, and it is the easiest way to fool yourself with
this generator. It happened during development: examples/memslave_zs reported 34/34 with an
empty predictor.
"""

import pathlib

import yaml

from quick_uvm.generator import Generator
from quick_uvm.models import ProjectConfig

_BASE = {
    "project": {"name": "r_tb", "author": "a@b.c"},
    "dut": {"name": "r", "clock": "clk", "reset": "rst_n", "external_reset": True},
    "agents": [
        {
            "name": "io",
            "interface": "io_if",
            "sequence_item": "io_item",
            "ports": {
                "inputs": [{"name": "din", "width": 8, "randomize": True}],
                "outputs": [{"name": "dout", "width": 8}],
            },
        }
    ],
    "tests": [{"name": "rand_test"}],
}

_STUBS = ("TODO: Replace this stub", "TODO: map the request")


def test_the_generated_stub_refuses_to_pass(tmp_path):
    """A fresh bench must FAIL until its DUT is modelled.

    Mutation-proved on Xcelium: before this, a fresh reg8 bench reported "20 Ran / 20
    Passed" with an empty seam. Now it is UVM_FATAL. Fill the seam -> 22/22 pass. Break
    the DUT -> 22/22 fail.
    """
    cfg = ProjectConfig.model_validate(_BASE)
    Generator(cfg).generate_all(tmp_path, backup=False)
    rm = (tmp_path / "r_reference_model.svh").read_text()

    assert "UNFILLED_PREDICTOR" in rm
    assert "uvm_fatal" in rm
    # the guard must sit INSIDE the seam: writing the model is what removes it, and that
    # is the intended way out. (Contrast the prefetch driver's EMPTY_TRANSFER guard, which
    # must sit OUTSIDE its seam because EMPTYING that one is the failure mode.)
    i = rm.index("pragma quickuvm custom prediction_logic begin")
    j = rm.index("pragma quickuvm custom prediction_logic end")
    assert i < rm.index("UNFILLED_PREDICTOR") < j

    # and it must name the legitimate escape, not just complain
    assert "scoreboards: []" in rm


def test_no_committed_example_ships_a_scoreboard_that_cannot_fail():
    """The repo gate. An example with an ENABLED scoreboard and an UNFILLED seam reports
    N/N passed against a DUT it never modelled.

    NB `fifo` and `wbx` DO leave the seam unfilled — but both set `analysis.scoreboards: []`,
    so no predictor is wired and the file is inert dead code. Their real checks live
    elsewhere (fifo's is a two-stream model in its smoke vseq; breaking the DUT's read path
    does make it fail).
    """
    offenders = []
    for y in sorted(pathlib.Path("examples").glob("*/*.yaml")):
        if y.stem != y.parent.name:
            continue
        cfg = yaml.safe_load(y.read_text())
        sbs = (cfg.get("analysis") or {}).get("scoreboards", None)
        enabled = sbs is None or len(sbs) > 0  # key absent => a scoreboard IS generated
        for rm in (y.parent / "gen").glob("*reference_model.svh"):
            if enabled and any(s in rm.read_text() for s in _STUBS):
                offenders.append(str(rm))
    assert not offenders, (
        "these examples ship an enabled scoreboard whose prediction seam is still the "
        f"generated stub — they cannot fail: {offenders}"
    )
