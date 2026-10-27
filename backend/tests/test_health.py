from app.db import DatabaseStatus


def test_health_ok_when_database_up(make_client):
    client = make_client(DatabaseStatus(reachable=True, latency_ms=1.5))
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == {"status": "up", "latency_ms": 1.5, "error": None}
    assert body["service"] == "Smart Campus Network Monitor"


def test_health_degraded_when_database_down(make_client):
    client = make_client(DatabaseStatus(reachable=False, error="ServerSelectionTimeoutError"))
    response = client.get("/api/health")
    assert response.status_code == 200  # API itself is alive
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"]["status"] == "down"
    assert body["database"]["error"] == "ServerSelectionTimeoutError"


def test_cors_allows_vite_dev_origin(make_client):
    client = make_client(DatabaseStatus(reachable=True, latency_ms=1))
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_blocks_unknown_origin(make_client):
    client = make_client(DatabaseStatus(reachable=True, latency_ms=1))
    response = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
