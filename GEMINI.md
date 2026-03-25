# Gemini CLI - Instructions for DeepReview

## Core Mandates
- **Expert Python Programmer:** Act as a senior Python developer. Prioritize readability, performance, and idiomatic Python ("Pythonic" code).
- **Tooling:** Use `uv` for all dependency management and execution tasks.

## Python Coding Standards
- **Style:** Follow PEP 8 guidelines.
- **Indentation:** Use **2 spaces** for indentation (as configured in `pyproject.toml`).
- **Formatting:** Use `ruff` for linting and formatting.
  - Run `uv run ruff check .` to lint.
  - Run `uv run ruff format .` to format.
- **Type Safety:** Always use type hints. Ensure they are correct and follow modern Python conventions (e.g., `list[str]` instead of `List[str]` for Python 3.9+).
- **Asynchronous Code:** The project relies on `asyncio`. Use `async`/`await` for I/O-bound operations.
- **future**: Never use the __future__ import for anything. We should be running on very modern python versions only.


## Dependency & Environment Management (`uv`)
- **Setup:** Use `uv sync` to install dependencies and create a `.venv`.
- **Execution:** Always use `python` to execute scripts.
  - Example: `python main.py <url> --mock`
- **Package Management:** Use `uv add <package>` to add new dependencies and `uv remove <package>` to remove them.
- **Lockfile:** Keep `uv.lock` updated by running `uv lock`.

## Project Architecture
- **Multi-Agent Review:** Logic is distributed across specialized markdown-defined agents in the `agents/` directory.
- **Hosts:** The `hosts/` directory abstracts source control providers (Gerrit, GitHub). New providers should implement the `Host` interface.
- **API Client:** `core/gemini_client.py` handles all Gemini API interactions. Avoid direct API calls elsewhere.
- **Synchronizer:** Use the `Vync` utility (from `vync.py`) for managing concurrent tasks and progress tracking.

## Testing & Validation
- Always verify changes by running the main entry point with the `--mock` flag if possible to save on API costs and time.
- Example: `python main.py <url> --mock`
