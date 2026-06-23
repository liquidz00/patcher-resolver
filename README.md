# patcher-resolver

A self-hosted macOS worker that resolves [Installomator](https://github.com/Installomator/Installomator) labels for [Patcher](https://github.com/liquidz00/Patcher)'s catalog API.

Many Installomator labels compute their download URL and version with shell that only runs correctly on a real Mac. Patcher's Linux ingest server resolves everything it can safely. The rest require macOS, and this worker is that half. For the full two-stage design, see Patcher's [Resolution architecture](https://docs.patcherctl.dev/en/latest/project/architecture/resolution.html). This README covers running the worker yourself.

> [!IMPORTANT]
> This worker is only useful as part of a self-hosted Patcher deployment. It writes into the catalog, which requires admin access that exists solely on a Patcher API you run yourself.

## How it works

A [Temporal](https://temporal.io) worker stays running on a macOS host. A daily schedule triggers the `ResolveCatalog` workflow, which:

1. Refreshes the local Installomator checkout and rebuilds its script from the current fragments.
2. Fetches the worklist from the API. The worklist is comprised of the labels Linux could not resolve, plus the ones macOS already owns.
3. Runs `./sweep/sweep.sh` per label, invoking `Installomator.sh` in a full macOS userspace and reading back the values it computes.
4. POSTs the arm64-canonical results back to the API.

Resolution runs one activity per label, fanned out and capped by `concurrency`. A label that fails its retries is counted, but will never cause the batch to fail.

## Prerequisites

- An always-on **macOS host**. macOS infrastructure is required (`codesign`, `osascript`, `hdiutil`).
- A reachable **Temporal** service (a local `temporal server start-dev`, or a self-hosted cluster).
- A local **Installomator checkout** that includes `assemble.sh`.
- A **self-hosted Patcher catalog API** that you operate, plus its admin token. The worker writes resolved values into the catalog, which only your own instance grants.
- A **GitHub PAT**, to avoid the 60 request/hour `api.github.com` limit Installomator's `*FromGit` helpers hit during resolution.
- **uv** and Python 3.14+.

## Install

```bash
git clone https://github.com/liquidz00/patcher-resolver
cd patcher-resolver
make install
```

## Configuration

Create a `.env` in the repo root. Field names map to upper-case environment variables (`patcher_admin_token` reads from `PATCHER_ADMIN_TOKEN`).

| Key | Required | Default | What it is |
|-----|----------|---------|------------|
| `patcher_admin_token` | yes | | Admin token for your self-hosted Patcher API. |
| `github_token` | yes | | GitHub PAT to lift the `api.github.com` rate limit during resolution. |
| `installomator_dir` | yes | | Path to your Installomator checkout (refreshed each run). |
| `resolve_label_script` | yes | | Path to `sweep/sweep.sh` in this repo. |
| `api_base_url` | no | `https://api.patcherctl.dev` | Base URL of your Patcher API. Point this at your self-hosted instance. |
| `temporal_address` | no | `localhost:7233` | Temporal frontend address. |
| `temporal_task_queue` | no | `patcher-resolver` | Task queue the worker and workflow share. |
| `concurrency` | no | `8` | Max labels resolved at once. |
| `label_timeout_minutes` | no | `10` | Per-label timeout. |
| `work_dir` | no | `~/.patcher-resolver` | Where per-run NDJSON results are written. |

## Running

1. Start Temporal (skip if one is already reachable):

```bash
temporal server start-dev
```

2. Start the worker and leave it running:

```bash
uv run python -m resolver.worker
```

3. Register the daily schedule once (04:30 UTC):

```bash
uv run python -m resolver.cli schedule
```

### Manually trigger

The resolver includes a CLI for one-off or manual invocations.

```bash
uv run python -m resolver.cli run-once                   # full set, resolve + publish
uv run python -m resolver.cli run-once --label firefox   # one label (repeatable)
uv run python -m resolver.cli run-once --no-publish       # resolve and write locally, skip the POST
```

## Keeping the worker always-on

The daily schedule lives in Temporal, but the worker that runs it is an ordinary process. To keep it alive across logouts, reboots, and crashes, run it under launchd. Save the following to `~/Library/LaunchAgents/dev.patcher.resolver.worker.plist`, adjusting the `uv` path and `WorkingDirectory` to match your install:

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

Then load it (this starts the worker now and relaunches it on every boot):

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.patcher.resolver.worker.plist
```

Confirm it came up with `launchctl print gui/$(id -u)/dev.patcher.resolver.worker`, and watch its output at the log paths you set above.

## Using your own Patcher API

To run the full pipeline you self-host the Patcher API. Point `api_base_url` at your instance and use that instance's admin token as `patcher_admin_token`. See Patcher's [self-hosting guide](https://docs.patcherctl.dev/en/latest/project/self-hosting.html) for the API side.

## Development

```bash
make dev        # install with dev extras (ruff)
make lint       # ruff format --check + ruff check
make format     # auto-format and fix
make lock       # update uv.lock
make upgrade    # bump deps and re-sync
```
