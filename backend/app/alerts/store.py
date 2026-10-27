from typing import Protocol

from pymongo.asynchronous.database import AsyncDatabase

from app.alerts.models import Alert

UPDATABLE_ALERT_FIELDS = frozenset(
    {"severity", "title", "message", "metrics", "affected_device_ids", "last_response_at", "updated_at", "state", "resolved_at", "acknowledged", "acknowledged_at", "quiet_cycles"}
)


def check_alert_updatable(fields: dict) -> None:
    unknown = set(fields) - UPDATABLE_ALERT_FIELDS
    if unknown:
        raise ValueError(f"Fields not updatable on an alert: {sorted(unknown)}")


class AlertStore(Protocol):
    async def insert_alerts(self, alerts: list[Alert]) -> None: ...
    async def update_alert(self, alert_id: str, fields: dict) -> bool: ...
    async def get_alert(self, alert_id: str) -> Alert | None: ...
    async def list_alerts(self, *, state: str | None = None, type: str | None = None, limit: int = 100) -> list[Alert]: ...


class MongoAlertStore:
    def __init__(self, db: AsyncDatabase) -> None:
        self._alerts = db["alerts"]

    async def ensure_indexes(self) -> None:
        await self._alerts.create_index([("state", 1), ("opened_at", -1)], name="state_opened")
        await self._alerts.create_index("dedupe_key", name="dedupe_key")

    async def insert_alerts(self, alerts: list[Alert]) -> None:
        docs = []
        for alert in alerts:
            doc = alert.model_dump()
            doc["_id"] = doc.pop("id")
            docs.append(doc)
        if docs:
            await self._alerts.insert_many(docs)

    async def update_alert(self, alert_id: str, fields: dict) -> bool:
        check_alert_updatable(fields)
        result = await self._alerts.update_one({"_id": alert_id}, {"$set": fields})
        return result.matched_count == 1

    @staticmethod
    def _to_model(doc: dict) -> Alert:
        data = dict(doc)
        data["id"] = data.pop("_id")
        return Alert.model_validate(data)

    async def get_alert(self, alert_id: str) -> Alert | None:
        doc = await self._alerts.find_one({"_id": alert_id})
        return self._to_model(doc) if doc else None

    async def list_alerts(self, *, state: str | None = None, type: str | None = None, limit: int = 100) -> list[Alert]:
        query = {k: v for k, v in {"state": state, "type": type}.items() if v is not None}
        docs = await self._alerts.find(query).sort("opened_at", -1).limit(limit).to_list(length=None)
        return [self._to_model(d) for d in docs]
