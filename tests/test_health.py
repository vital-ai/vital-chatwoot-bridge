"""
Tests for health check endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from vital_chatwoot_bridge.main import app

client = TestClient(app)


def test_health_check():
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_check_response_model():
    """Test that health check returns correct response model."""
    response = client.get("/health")
    data = response.json()
    assert "status" in data
    assert isinstance(data["status"], str)
    assert data["status"] == "ok"
