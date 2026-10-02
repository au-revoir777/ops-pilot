"""Test configuration for OpsPilot API tests."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def app():
    """Create a fresh FastAPI app instance for testing."""
    return create_app()


@pytest.fixture()
def client(app):
    """Synchronous test client for the API."""
    return TestClient(app)
