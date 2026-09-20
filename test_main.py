# Requires the db and redis services (docker-compose) to be running.
import io

import pytest
from fastapi.testclient import TestClient

from main import app

API_KEY = "changeme"
HEADERS = {"X-API-KEY": API_KEY}
FAKE_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_upload_file(client):
    file_content = b"1. What is the capital of France?\nA) Paris B) London"
    files = {"file": ("sample.txt", io.BytesIO(file_content), "text/plain")}

    response = client.post("/api/v1/upload", files=files, headers=HEADERS)

    assert response.status_code == 200
    assert "document_id" in response.json()


def test_get_status(client):
    response = client.get(f"/api/v1/documents/{FAKE_ID}/status", headers=HEADERS)

    assert response.status_code == 404


def test_unauthorized(client):
    response = client.get(f"/api/v1/documents/{FAKE_ID}/status")

    assert response.status_code == 401
