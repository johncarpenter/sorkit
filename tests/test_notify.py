"""Tests for sorkit.notify — notification dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sorkit.notify import (
    _build_message,
    _build_status,
    _notify_file,
    send_notifications,
)


class TestBuildStatus:
    def test_target_met(self):
        assert _build_status("TARGET_MET") == "COMPLETE"

    def test_all_pass(self):
        assert _build_status("ALL_PASS") == "COMPLETE"

    def test_plateau(self):
        assert _build_status("PLATEAU") == "CONVERGED"

    def test_diminishing(self):
        assert _build_status("DIMINISHING") == "CONVERGED"

    def test_max_attempts(self):
        assert _build_status("MAX_ATTEMPTS") == "CEILING HIT"

    def test_consecutive_failures(self):
        assert _build_status("CONSECUTIVE_FAILURES") == "NEEDS ATTENTION"

    def test_oracle_error(self):
        assert _build_status("ORACLE_ERROR") == "NEEDS ATTENTION"

    def test_unknown(self):
        assert _build_status("SOMETHING_ELSE") == "STOPPED"


class TestBuildMessage:
    def test_contains_all_fields(self):
        msg = _build_message(
            project_name="My Project",
            layer_name="search",
            score="0.8500",
            attempts=10,
            keeps=5,
            stop_reason="TARGET_MET",
        )
        assert "My Project" in msg
        assert "search" in msg
        assert "COMPLETE" in msg
        assert "TARGET_MET" in msg
        assert "0.8500" in msg
        assert "10" in msg
        assert "5 kept" in msg
        assert "T" in msg  # timestamp contains T


class TestNotifyFile:
    def test_creates_file(self, tmp_path: Path):
        _notify_file("test message", tmp_path)
        log = tmp_path / "reports" / "notifications.log"
        assert log.exists()
        content = log.read_text()
        assert "---" in content
        assert "test message" in content

    def test_appends_to_existing(self, tmp_path: Path):
        _notify_file("first", tmp_path)
        _notify_file("second", tmp_path)
        log = tmp_path / "reports" / "notifications.log"
        content = log.read_text()
        assert content.count("---") == 2
        assert "first" in content
        assert "second" in content


@pytest.mark.asyncio(loop_scope="function")
class TestSendNotifications:
    async def test_file_always_notified(self, tmp_path: Path):
        result = await send_notifications(
            project_name="Test",
            layer_name="search",
            score="0.85",
            attempts=5,
            keeps=3,
            stop_reason="TARGET_MET",
            project_dir=tmp_path,
        )
        assert "file" in result
        log = tmp_path / "reports" / "notifications.log"
        assert log.exists()

    async def test_slack_when_env_set(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with patch("sorkit.notify._notify_slack", new_callable=AsyncMock) as mock_slack:
            result = await send_notifications(
                project_name="Test",
                layer_name="search",
                score="0.85",
                attempts=5,
                keeps=3,
                stop_reason="TARGET_MET",
                project_dir=tmp_path,
            )
            assert "slack" in result
            mock_slack.assert_called_once()

    async def test_no_slack_without_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        result = await send_notifications(
            project_name="Test",
            layer_name="search",
            score="0.85",
            attempts=5,
            keeps=3,
            stop_reason="TARGET_MET",
            project_dir=tmp_path,
        )
        assert "slack" not in result

    async def test_email_when_env_set(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("NOTIFY_EMAIL", "test@example.com")

        with patch("sorkit.notify._notify_email", new_callable=AsyncMock) as mock_email:
            result = await send_notifications(
                project_name="Test",
                layer_name="search",
                score="0.85",
                attempts=5,
                keeps=3,
                stop_reason="TARGET_MET",
                project_dir=tmp_path,
            )
            assert "email" in result
            mock_email.assert_called_once()

    async def test_desktop_called(self, tmp_path: Path):
        with patch("sorkit.notify._notify_desktop", new_callable=AsyncMock) as mock_desktop:
            result = await send_notifications(
                project_name="Test",
                layer_name="search",
                score="0.85",
                attempts=5,
                keeps=3,
                stop_reason="TARGET_MET",
                project_dir=tmp_path,
            )
            assert "desktop" in result
            mock_desktop.assert_called_once()

    async def test_channel_failure_doesnt_block_others(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with patch("sorkit.notify._notify_slack", new_callable=AsyncMock, side_effect=Exception("boom")):
            result = await send_notifications(
                project_name="Test",
                layer_name="search",
                score="0.85",
                attempts=5,
                keeps=3,
                stop_reason="TARGET_MET",
                project_dir=tmp_path,
            )
            # Slack failed but file should still work
            assert "file" in result
            assert "slack" not in result
