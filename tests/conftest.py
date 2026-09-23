"""Shared pytest fixtures."""

import pytest

from vital_chatwoot_bridge.core.config import get_settings


@pytest.fixture(autouse=True)
def _dry_run_off_by_default(monkeypatch):
    """Keep a local .env's CW_BRIDGE__app__dry_run from leaking into tests.

    Tests that exercise dry-run enable it explicitly (see test_dry_run.py).
    """
    monkeypatch.setattr(get_settings(), "dry_run", False)
    monkeypatch.setattr(get_settings(), "dry_run_record_notes", True)
