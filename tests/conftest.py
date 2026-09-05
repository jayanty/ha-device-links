"""Shared fixtures for the Device Links test suite."""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Load custom_components/device_links in every test."""
    yield
