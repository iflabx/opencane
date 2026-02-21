# Repository Guidelines

## Project Structure & Module Organization
- `opencane/`: main application code (agent loop, hardware runtime, APIs, storage, vision, safety, CLI).
- `tests/`: unit and integration tests (`test_*.py`), including hardware control/API and storage migration coverage.
- `docs/`: architecture, deployment, operations, and API references.
- `scripts/`: utility and smoke-test scripts (replay, control API checks, backup/restore helpers).
- `bridge/`: channel bridge assets.

## Local-only Directories Policy
- `local-docs/` and `local-scripts/` are reserved for machine-local notes and scripts.
- Do not stage, commit, or push files under these two directories.
- Keep both entries in `.gitignore`; treat this as a hard repository rule.
- If content must be shared, move it to tracked paths such as `docs/` or `scripts/`.

## Build, Test, and Development Commands
- Install (dev):
  ```bash
  pip install -e ".[dev]"
  ```
- Run full test suite:
  ```bash
  pytest -q
  ```
- Run focused tests:
  ```bash
  pytest -q tests/test_hardware_runtime.py
  ```
- Lint:
  ```bash
  ruff check
  ```
- Start hardware runtime locally:
  ```bash
  opencane hardware serve --adapter mock --logs
  ```

## Coding Style & Naming Conventions
- Language: Python 3.11+.
- Style: 4-space indentation, type hints for public interfaces, concise docstrings on modules/classes.
- Naming: `snake_case` for functions/variables/files, `PascalCase` for classes, `UPPER_CASE` for constants.
- Keep changes minimal and scoped; prefer explicit, readable logic over clever shortcuts.
- Use `ruff` for lint compliance before committing.

## Testing Guidelines
- Framework: `pytest` (with `pytest-asyncio` for async flows).
- Add/adjust tests for every behavior change, especially for:
  - runtime event handling,
  - control API contract compatibility,
  - storage migrations and retention behavior.
- Test files should follow `tests/test_<feature>.py`; test names should describe expected behavior.

## Commit & Pull Request Guidelines
- Follow Conventional Commit style seen in history, e.g.:
  - `feat(runtime): ...`
  - `feat(api): ...`
  - `docs(ops): ...`
- Keep commits focused by subsystem (runtime, control-plane, storage, docs).
- PRs should include:
  - what changed and why,
  - risk/compatibility notes (especially hardware/protocol impact),
  - test evidence (`pytest -q`, targeted tests),
  - doc updates when API/config behavior changes.

## Security & Configuration Tips
- Never commit real API keys or device tokens.
- Use config profiles and environment-specific settings (`CONFIG_PROFILE_*.json`).
- For hardware/control API changes, preserve backward compatibility and keep new capabilities optional by default.
