"""
The resolution pipeline: refresh Installomator, fetch the macOS worklist from the
API, run ``sweep.sh`` per label on this Mac, and write the results. Pure I/O; the
Temporal activities are thin wrappers around these. Writing locally is the first
cut; the production change is POSTing the results to the API instead.
"""

import json
import os
import subprocess
from pathlib import Path

import httpx

from resolver.config import get_settings


def _work_dir() -> Path:
    return Path(get_settings().work_dir).expanduser()


def update_installomator() -> str:
    """``git pull`` the Installomator checkout; return the short HEAD sha."""
    d = get_settings().installomator_dir
    subprocess.run(
        ["git", "-C", d, "pull", "--ff-only"], check=True, capture_output=True, text=True
    )
    head = subprocess.run(
        ["git", "-C", d, "rev-parse", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return head.stdout.strip()


def fetch_worklist() -> list[str]:
    """
    The macOS worklist from ``GET /admin/labels/unresolved``: labels with a
    dynamic field the Linux resolver couldn't fill, plus labels macOS already
    owns (re-resolved each run to stay fresh). Scopes the Mini to what Linux
    genuinely can't do rather than the whole catalog.
    """
    settings = get_settings()
    response = httpx.get(
        f"{settings.api_base_url}/admin/labels/unresolved",
        headers={"Authorization": f"Bearer {settings.patcher_admin_token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["labels"]


def resolve_label(label: str) -> dict:
    """
    Resolve one label with ``sweep.sh`` and return its result object.

    ``sweep.sh`` prints a JSON array grouped by label (one element here, since we
    pass a single label) to stdout, with per-resolution progress on stderr. A
    null ``downloadURL`` / ``appNewVersion`` is a valid result, not a failure;
    only a non-zero exit or unparseable output raises, and Temporal retries it.
    """
    settings = get_settings()
    # Inherit the real environment (PATH/HOME for arch, hdiutil, curl) and overlay
    # the GitHub token Installomator's *FromGit helpers need for the api.github.com limit.
    env = {
        **os.environ,
        "GITHUB_TOKEN": settings.github_token,
        "GH_TOKEN": settings.github_token,
    }
    result = subprocess.run(
        ["/bin/zsh", "--no-rcs", settings.resolve_label_script, label],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=settings.label_timeout_minutes * 60,
    )
    grouped = json.loads(result.stdout)
    return grouped[0] if grouped else {"label": label, "results": []}


def write_results(results: list[dict], stamp: str) -> dict:
    """Write the per-label results to a timestamped NDJSON file; return path + count."""
    out_dir = _work_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"mini-{stamp}.ndjson"
    with path.open("w") as file:
        for record in results:
            file.write(json.dumps(record) + "\n")
    return {"ndjson_path": str(path), "resolved": len(results)}
