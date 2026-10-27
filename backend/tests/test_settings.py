from app.config.settings import Settings


def test_defaults(monkeypatch):
    for name in ("MONGODB_URI", "MONGODB_DB_NAME", "MONGODB_SERVER_SELECTION_TIMEOUT_MS", "ENSURE_INDEXES_ON_STARTUP"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.mongodb_db_name == "campus_noc"
    assert settings.mongodb_server_selection_timeout_ms == 2000
    assert settings.ensure_indexes_on_startup is True


def test_env_override(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example:27017")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    settings = Settings(_env_file=None)
    assert settings.mongodb_uri == "mongodb://example:27017"
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_probe_defaults(monkeypatch):
    for name in ("PROBE_COUNT", "PROBE_TIMEOUT_S", "PROBE_INTERVAL_S", "ICMP_BACKEND", "MONITOR_ATTACHED_TO"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert (settings.probe_count, settings.probe_timeout_s, settings.probe_interval_s) == (5, 1.0, 0.2)
    assert settings.icmp_backend == "auto" and settings.monitor_attached_to == "core-switch"


import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "name,value",
    [("PROBE_COUNT", "0"), ("PROBE_COUNT", "500"), ("PROBE_TIMEOUT_S", "0"), ("PROBE_INTERVAL_S", "0.01"), ("ICMP_BACKEND", "telepathy")],
)
def test_invalid_probe_settings_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
