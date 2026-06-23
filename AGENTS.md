# AGENTS.md

Guidance for AI agents (Claude Code, Cursor, and others) working in this repo. `CLAUDE.md` is a symlink to this file, so this is the single source of truth.

## What this is

A [Temporal](https://temporal.io) worker that resolves [Installomator](https://github.com/Installomator/Installomator) labels (download URL and version) for [Patcher](https://github.com/liquidz00/Patcher)'s catalog API, by running the real `Installomator.sh` in a macOS userspace. `README.md` has the full picture.

## Layout

- `resolver/config.py` — pydantic-settings, read from `.env`.
- `resolver/resolve.py` — the pipeline and all real I/O: refresh Installomator, fetch the worklist, run `sweep.sh` per label, write NDJSON, publish results.
- `resolver/activities.py` — thin Temporal activities wrapping `resolve.py` via `asyncio.to_thread`.
- `resolver/workflows.py` — the `ResolveCatalog` workflow. Keep it deterministic: reference activities by name and keep subprocess/httpx imports out of this module (the workflow sandbox rejects them).
- `resolver/worker.py`, `resolver/cli.py` — the worker process and the run-once/schedule CLI.
- `sweep/sweep.sh` — the per-label resolver that drives `Installomator.sh`.

## Working here

- uv-managed, Python 3.14. `make dev` to install, `make lint` (ruff format check + lint), `make format` to autofix.
- Secrets live in `.env` (gitignored): `PATCHER_ADMIN_TOKEN`, `GITHUB_TOKEN`. Never commit them or write them into code or docs.
- This is a public repo. Do not name the host's specific hardware or location in any committed file. Say "self-hosted macOS host" or "the worker", never the machine model.
