# Python style — the QuickUVM generator codebase

Guidelines for `quick_uvm/` and `tests/`. The aim matches the project philosophy
(*simple by default, powerful when needed*): **rules are enforced by tooling, not
memorized** — run the tools, don't learn a rulebook.

## Tooling (one tool per job)

| Job | Tool | Config |
|---|---|---|
| Format + import-sort + lint | **Ruff** | `[tool.ruff]` in `pyproject.toml` |
| Static types | **mypy** (+ `pydantic.mypy` plugin) | `[tool.mypy]` in `pyproject.toml` |
| Local pre-commit loop | **pre-commit** | `.pre-commit-config.yaml` |
| CI gate | GitHub Actions | `.github/workflows/ci.yml` (`python` job) |

Ruff replaces the `black + isort + flake8 (+plugins)` stack with one fast tool, and
pylint is intentionally avoided (noisy/slow → raises the contributor barrier).

## Setup

```bash
pip install -e ".[dev]"
pre-commit install          # optional: run ruff+mypy on every commit
```

Everyday commands:

```bash
ruff format .               # format
ruff check --fix .          # lint + auto-fix
mypy                        # type-check quick_uvm/
pytest -q                   # unit tests
```

CI runs exactly these four on every PR; a green local run = a green CI `python` job.

## Conventions

- **Line length 88** (Ruff/Black default).
- **PEP 8**, enforced by Ruff (`E`, `F`, `W`); imports sorted by Ruff (`I`);
  modern-Python idioms by `UP` (pyupgrade). `from __future__ import annotations` at the
  top of modules with type hints.
- **Type hints on all public functions/methods.** Pydantic v2 models are the config
  schema (`models.py`) — keep them fully typed; the `pydantic.mypy` plugin checks them.
- **Docstrings**: module + public class/function. Keep them short and imperative; no
  enforced docstring format (don't over-formalize for a small codebase).
- **Tests** live in `tests/`, named `test_*.py`, one behaviour per test; long assertion
  strings are exempt from line-length (`per-file-ignores`).

## Strictness is a ratchet, not a wall

To keep the entry barrier low, the baseline starts lenient and tightens over time:

1. **Now:** Ruff `E, F, W, I, UP`; mypy with `check_untyped_defs` but
   `disallow_untyped_defs = false`, `ignore_missing_imports = true`.
2. **Next ratchet:** add Ruff `B` (bugbear), `C4`, `SIM`, `RUF`; turn on mypy
   `disallow_untyped_defs` for `quick_uvm/`.
3. **Later:** consider mypy `--strict` for `quick_uvm/` (tests stay lenient).

Tighten only when the current level is clean and green — never land a level that paints
contributors into red CI on day one.
