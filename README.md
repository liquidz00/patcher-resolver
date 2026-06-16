# patcher-resolver

Resolves Installomator labels for [Patcher](https://github.com/liquidz00/Patcher) natively on the Mac Mini, instead of (eventually: in front of) the GitHub macOS runner. It's the same `resolveLabel.sh` the GitHub job runs, driven by a Temporal workflow.

**Currently shadow mode:** it resolves the worklist and writes the NDJSON locally, it does **not** POST to the API, so it can't affect production or race the GitHub job. The `diff` command compares the Mini's output against the GitHub runner's to confirm the environment produces equivalent values before we ever promote it.

## How it works

```
ShadowResolve workflow:
  git pull Installomator  →  GET /admin/labels/unresolved  →  resolveLabel.sh --json  →  write NDJSON (no POST)
```

Then `diff` downloads the GitHub runner's latest `resolved-labels-ndjson` artifact and compares `downloadURL` / `appNewVersion` per label.

## Setup (on the Mini)

```bash
cd ~/GitHub/patcher-resolver
uv sync

# Clones the resolver needs (kept fresh with `git pull` each run):
git clone https://github.com/Installomator/Installomator.git ~/GitHub/Installomator
git clone https://github.com/liquidz00/Patcher.git ~/GitHub/Patcher   # for resolveLabel.sh

cp .env.example .env   # then fill in
```

`.env` needs the `PATCHER_ADMIN_TOKEN`, a GitHub PAT, and the absolute paths to the two checkouts.

## Run

Reuses the Temporal dev server already running on the Mini.

```bash
uv run python -m resolver.worker          # the worker (or add a launchd agent later)
uv run python -m resolver.cli run-once    # resolve now → writes ~/.patcher-resolver/mini-<ts>.ndjson
uv run python -m resolver.cli diff        # compare against GitHub's latest run
```

Once shadow comparison looks clean, the promotion is small: the workflow POSTs to `/admin/labels/resolved` instead of writing locally, scheduled before the GitHub job, and the GitHub job becomes a freshness-gated fallback.
