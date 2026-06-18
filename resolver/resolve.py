"""
The resolution pipeline: refresh Installomator, fetch the macOS worklist from the
API, run ``sweep.sh`` per label on this Mac, write the results, and publish the
arm64-canonical values back to the API. Pure I/O; the Temporal activities are
thin wrappers around these.
"""

import json
import os
import subprocess
from pathlib import Path

import httpx

from resolver.config import get_settings

_PRIMARY_ARCH = "arm64"  # canonical arch when a label resolves per-arch; the x86_64 URL is dropped


def _work_dir() -> Path:
    return Path(get_settings().work_dir).expanduser()


def update_installomator() -> str:
    """
    Refresh the Installomator checkout and rebuild its script from fragments.

    ``main``'s committed ``Installomator.sh`` lags its own ``fragments/`` (it's
    reassembled only periodically), so the newest labels exist as fragments the
    runnable script doesn't yet know. ``assemble.sh -s`` rebuilds it from current
    fragments; ``reset --hard`` first discards the prior run's rebuilt script so
    the checkout is clean before fetching. Returns the short HEAD sha.
    """
    d = get_settings().installomator_dir
    subprocess.run(
        ["git", "-C", d, "fetch", "origin", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", d, "reset", "--hard", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["/bin/zsh", "--no-rcs", f"{d}/assemble.sh", "-s"],
        check=True,
        capture_output=True,
        text=True,
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
    # Inherit the real environment (PATH/HOME for arch, hdiutil, curl); overlay the
    # GitHub token (api.github.com limit) and the Installomator checkout sweep.sh reads.
    env = {
        **os.environ,
        "GITHUB_TOKEN": settings.github_token,
        "GH_TOKEN": settings.github_token,
        "INSTALLOMATOR_DIR": settings.installomator_dir,
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


def _pick_result(results: list[dict]) -> dict | None:
    """
    Collapse a label's per-axis results to one, arm64-canonical.

    Prefer the ``arm64`` result; fall back to ``any`` (labels that don't branch
    on arch resolve once) or the first result. The ``x86_64`` URL is dropped on
    purpose — the catalog is single-URL and the arch-aware install happens in
    Installomator at runtime.
    """
    by_arch = {result.get("arch"): result for result in results}
    return by_arch.get(_PRIMARY_ARCH) or by_arch.get("any") or (results[0] if results else None)


def _to_resolved_record(grouped: dict) -> dict:
    """One ``sweep.sh`` per-label result -> the flat record ``/admin/labels/resolved`` ingests."""
    chosen = _pick_result(grouped.get("results") or [])
    download_url = chosen.get("downloadURL") if chosen else None
    app_new_version = chosen.get("appNewVersion") if chosen else None
    return {
        "label": grouped.get("label"),
        "ok": bool(download_url or app_new_version),
        "downloadURL": download_url,
        "appNewVersion": app_new_version,
    }


def publish_results(results: list[dict]) -> dict:
    """
    POST the collapsed records to ``/admin/labels/resolved`` and return the
    endpoint's ingest summary. Records are arm64-canonical, flat
    ``resolveLabel.sh``-shaped lines; the endpoint validates each value and
    updates only labels the Linux ingest already created.
    """
    settings = get_settings()
    body = "\n".join(json.dumps(_to_resolved_record(grouped)) for grouped in results)
    response = httpx.post(
        f"{settings.api_base_url}/admin/labels/resolved",
        headers={
            "Authorization": f"Bearer {settings.patcher_admin_token}",
            "Content-Type": "application/x-ndjson",
        },
        content=body,
        timeout=300,
    )
    response.raise_for_status()
    return response.json()
