# patcher-resolver

A self-hosted macOS worker that resolves [Installomator](https://github.com/Installomator/Installomator) labels for [Patcher](https://github.com/liquidz00/Patcher)'s catalog API.

Many Installomator labels compute their download URL and version with shell that only runs correctly on a real Mac. Patcher's Linux ingest server resolves everything it safely can; the rest needs macOS userspace, and this worker is that macOS half. For the full two-stage design, see Patcher's [Resolution architecture](https://docs.patcherctl.dev/project/architecture/resolution.html). This README covers running the worker yourself.

## How it works

A [Temporal](https://temporal.io) worker stays running on a macOS host. A daily schedule triggers the `ResolveCatalog` workflow, which:

1. Refreshes the local Installomator checkout and rebuilds its script from the current fragments.
2. Fetches the worklist from the API (`GET /admin/labels/unresolved`): the labels Linux could not resolve, plus the ones macOS already owns.
3. Runs `sweep.sh` per label, invoking the real `Installomator.sh` in a full macOS userspace and reading back the values it computes.
4. POSTs the arm64-canonical results to the API (`POST /admin/labels/resolved`).

Resolution runs one activity per label, fanned out and capped by `concurrency`. A label that fails its retries is counted, not fatal to the batch.

## Prerequisites

- An always-on **macOS host**. Real macOS userspace is the whole point (codesign, osascript, hdiutil).
- A reachable **Temporal** service (a local `temporal server start-dev`, or a self-hosted cluster).
- A local **Installomator checkout** that includes `assemble.sh`.
- A **Patcher catalog API** you can write to (the hosted `api.patcherctl.dev`, or your own instance) plus its admin token.
- A **GitHub PAT**, to avoid the 60 request/hour `api.github.com` limit Installomator's `*FromGit` helpers hit during resolution.
- **uv** and Python 3.14+.

## Install

```console
git clone https://github.com/liquidz00/patcher-resolver
cd patcher-resolver
make install
```

## Configuration

Create a `.env` in the repo root. Field names map to upper-case environment variables (`patcher_admin_token` reads from `PATCHER_ADMIN_TOKEN`).

| Key | Required | Default | What it is |
|-----|----------|---------|------------|
| `patcher_admin_token` | yes | | Bearer token for the API's `/admin/*` routes. |
| `github_token` | yes | | GitHub PAT to lift the `api.github.com` rate limit during resolution. |
| `installomator_dir` | yes | | Path to your Installomator checkout (refreshed each run). |
| `resolve_label_script` | yes | | Path to `sweep/sweep.sh` in this repo. |
| `api_base_url` | no | `https://api.patcherctl.dev` | Base URL of the Patcher API to read from and write to. |
| `temporal_address` | no | `localhost:7233` | Temporal frontend address. |
| `temporal_task_queue` | no | `patcher-resolver` | Task queue the worker and workflow share. |
| `concurrency` | no | `8` | Max labels resolved at once. |
| `label_timeout_minutes` | no | `10` | Per-label timeout. |
| `work_dir` | no | `~/.patcher-resolver` | Where per-run NDJSON results are written. |

Never commit `.env`. It holds two secrets, the admin token and the GitHub PAT.

## Running

Start Temporal (skip if one is already reachable):

```console
temporal server start-dev
```

Start the worker and leave it running:

```console
uv run python -m resolver.worker
```

Register the daily schedule once (04:30 UTC):

```console
uv run python -m resolver.cli schedule
```

Or trigger a run by hand:

```console
uv run python -m resolver.cli run-once                   # full set, resolve + publish
uv run python -m resolver.cli run-once --label firefox   # one label (repeatable)
uv run python -m resolver.cli run-once --no-publish       # resolve and write locally, skip the POST
```

## Keeping the worker always-on

The schedule lives in Temporal, but the worker is just a process, so it needs something to restart it across reboots and crashes. A minimal LaunchAgent (adjust the `uv` path and `WorkingDirectory`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.patcher.resolver.worker</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/uv</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>resolver.worker</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/patcher-resolver</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/patcher-resolver.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/patcher-resolver.err.log</string>
</dict>
</plist>
```

Load it with:

```console
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.patcher.resolver.worker.plist
```

## Using your own Patcher API

Point `api_base_url` at your instance. The worker reads `GET /admin/labels/unresolved` and writes `POST /admin/labels/resolved`, both with `patcher_admin_token` as a Bearer token. Those routes are token-gated and fail closed, so the token must match the API's `PATCHER_API_ADMIN_TOKEN`. See Patcher's [self-hosting guide](https://docs.patcherctl.dev/project/self-hosting.html) for the API side.

## Development

```console
make dev        # install with dev extras (ruff)
make lint       # ruff format --check + ruff check
make format     # auto-format and fix
make lock       # update uv.lock
make upgrade    # bump deps and re-sync
```
