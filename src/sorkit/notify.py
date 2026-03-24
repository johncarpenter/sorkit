"""Notification dispatcher — file, Slack, email, desktop."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


def _build_status(stop_reason: str) -> str:
    """Map stop reason to human-readable status."""
    if stop_reason in ("TARGET_MET", "ALL_PASS"):
        return "COMPLETE"
    if stop_reason in ("PLATEAU", "DIMINISHING"):
        return "CONVERGED"
    if stop_reason == "MAX_ATTEMPTS":
        return "CEILING HIT"
    if stop_reason in ("CONSECUTIVE_FAILURES", "ORACLE_ERROR"):
        return "NEEDS ATTENTION"
    return "STOPPED"


def _build_message(
    project_name: str,
    layer_name: str,
    score: str,
    attempts: int,
    keeps: int,
    stop_reason: str,
) -> str:
    """Build the notification message text."""
    status = _build_status(stop_reason)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"{project_name} — {layer_name} {status}\n"
        f"Reason: {stop_reason}\n"
        f"Score: {score}\n"
        f"Attempts: {attempts} ({keeps} kept)\n"
        f"Time: {timestamp}"
    )


async def send_notifications(
    project_name: str,
    layer_name: str,
    score: str,
    attempts: int,
    keeps: int,
    stop_reason: str,
    project_dir: Path,
) -> list[str]:
    """Send notifications to all configured channels.

    Returns a list of channels that were notified successfully.
    Each channel is independent — one failing doesn't block others.
    """
    message = _build_message(
        project_name, layer_name, score, attempts, keeps, stop_reason,
    )
    status = _build_status(stop_reason)
    notified: list[str] = []

    # File notification (always)
    try:
        _notify_file(message, project_dir)
        notified.append("file")
    except Exception:
        pass

    # Slack
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if webhook_url:
        try:
            await _notify_slack(message, webhook_url)
            notified.append("slack")
        except Exception:
            pass

    # Email
    email = os.environ.get("NOTIFY_EMAIL", "")
    if email:
        try:
            await _notify_email(
                message, email, f"{project_name}: {layer_name} {status}",
            )
            notified.append("email")
        except Exception:
            pass

    # Desktop
    try:
        await _notify_desktop(
            project_name, f"{layer_name}: {status} ({score})",
        )
        notified.append("desktop")
    except Exception:
        pass

    return notified


def _notify_file(message: str, project_dir: Path) -> None:
    """Append notification to reports/notifications.log."""
    notify_file = Path(os.environ.get("NOTIFY_FILE", ""))
    if not notify_file.is_absolute():
        notify_file = project_dir / "reports" / "notifications.log"
    notify_file.parent.mkdir(parents=True, exist_ok=True)
    with open(notify_file, "a") as f:
        f.write("---\n")
        f.write(message)
        f.write("\n\n")


async def _notify_slack(message: str, webhook_url: str) -> None:
    """Post notification to Slack webhook."""
    payload = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Run blocking urllib in a thread to keep async
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10))


async def _notify_email(message: str, email: str, subject: str) -> None:
    """Send email via local mail command."""
    proc = await asyncio.create_subprocess_exec(
        "mail", "-s", subject, email,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate(input=message.encode("utf-8"))


async def _notify_desktop(title: str, body: str) -> None:
    """Send desktop notification (macOS or Linux)."""
    if sys.platform == "darwin":
        script = f'display notification "{body}" with title "{title}"'
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    elif sys.platform == "linux":
        proc = await asyncio.create_subprocess_exec(
            "notify-send", title, body,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
