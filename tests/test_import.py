"""Tests for mikrus_mcp package."""

import pytest


def test_import():
    """Test that the package can be imported."""
    import mikrus_mcp

    assert mikrus_mcp.__version__ == "0.1.0"
