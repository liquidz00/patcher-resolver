"""
The resolution pipeline itself: refresh Installomator, fetch the worklist, run
``resolveLabel.sh``, and write the NDJSON. Pure I/O; the Temporal activities are
thin wrappers around these. This is the code that becomes production once the
shadow comparison checks out (the only change then is POSTing instead of writing).
"""

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
    """GET the labels the Linux resolver couldn't resolve (the macOS worklist)."""
    settings = get_settings()
    response = httpx.get(
        f"{settings.api_base_url}/admin/labels/unresolved",
        headers={"Authorization": f"Bearer {settings.patcher_admin_token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["labels"]


def _run_resolver(labels: list[str]) -> str:
    """Run ``resolveLabel.sh --json`` over the worklist; return the NDJSON."""
    if not labels:
        return ""
    settings = get_settings()
    # Inherit the real environment (PATH/HOME for arch, osascript, hdiutil, curl)
    # and overlay what the script and Installomator's *FromGit helpers expect.
    env = {
        **os.environ,
        "INSTALLOMATOR_DIR": settings.installomator_dir,
        "GITHUB_TOKEN": settings.github_token,
        "GH_TOKEN": settings.github_token,
    }
    result = subprocess.run(
        ["/bin/zsh", "--no-rcs", settings.resolve_label_script, "--json", "--jobs", "8", *labels],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=settings.resolve_timeout_minutes * 60,
    )
    return result.stdout


def resolve_to_file(labels: list[str], stamp: str) -> dict:
    """
    Resolve the worklist and write the NDJSON to a timestamped file.

    Returns only the path and resolved count — the NDJSON itself stays inside the
    activity and never crosses into Temporal's workflow history (where it would
    blow the payload-size limit).
    """
    ndjson = _run_resolver(labels)
    out_dir = _work_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"mini-{stamp}.ndjson"
    path.write_text(ndjson)
    resolved = len([line for line in ndjson.splitlines() if line.strip()])
    return {"ndjson_path": str(path), "resolved": resolved}
