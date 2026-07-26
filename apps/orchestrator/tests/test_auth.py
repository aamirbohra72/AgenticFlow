import pytest
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.fixture
def client():
    return APIClient()


@override_settings(API_KEY="test-secret-key")
def test_health_is_public(client):
    res = client.get("/api/health/")
    assert res.status_code in (200, 503)


@override_settings(API_KEY="test-secret-key")
def test_query_requires_api_key(client):
    res = client.post("/api/query/", {"query": "Where is my order #1234?"}, format="json")
    assert res.status_code == 401


@override_settings(API_KEY="test-secret-key")
def test_query_rejects_bad_key(client):
    res = client.post(
        "/api/query/",
        {"query": "Where is my order #1234?"},
        format="json",
        HTTP_X_API_KEY="wrong",
    )
    assert res.status_code == 401


@override_settings(API_KEY="test-secret-key")
def test_metrics_requires_api_key(client):
    res = client.get("/api/metrics/")
    assert res.status_code == 401

    res_ok = client.get("/api/metrics/", HTTP_X_API_KEY="test-secret-key")
    assert res_ok.status_code == 200
    assert "counters" in res_ok.json()
