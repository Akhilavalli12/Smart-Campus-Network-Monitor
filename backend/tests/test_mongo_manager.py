from app.config.settings import Settings
from app.db import MongoManager


async def test_ping_reports_unreachable_database_without_raising():
    # Port 1 on localhost: nothing listens there, so the driver must time out quickly.
    settings = Settings(
        _env_file=None,
        mongodb_uri="mongodb://127.0.0.1:1",
        mongodb_server_selection_timeout_ms=300,
    )
    manager = MongoManager(settings)
    try:
        status = await manager.ping()
    finally:
        await manager.close()
    assert status.reachable is False
    assert status.latency_ms is None
    assert status.error  # exception class name, e.g. ServerSelectionTimeoutError
