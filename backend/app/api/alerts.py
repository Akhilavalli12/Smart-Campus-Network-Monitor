"""Alert endpoints: read, summarise, acknowledge. Alerts are created and resolved by the alert engine only."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.alerts.models import Alert, AlertType
from app.alerts.store import AlertStore
from app.api.dependencies import get_alert_store
from app.network_model.errors import NotFoundError

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertSummary(BaseModel):
    active: int
    critical: int
    warning: int
    unacknowledged: int
    by_type: dict[str, int]


@router.get("", response_model=list[Alert])
async def list_alerts(
    state: str | None = Query(None, pattern="^(open|resolved)$"),
    type: AlertType | None = None,
    limit: int = Query(100, ge=1, le=1000),
    store: AlertStore = Depends(get_alert_store),
) -> list[Alert]:
    """Newest first. `state=open` for active alerts."""
    return await store.list_alerts(state=state, type=type.value if type else None, limit=limit)


@router.get("/summary", response_model=AlertSummary)
async def alert_summary(store: AlertStore = Depends(get_alert_store)) -> AlertSummary:
    active = await store.list_alerts(state="open", limit=1000)
    by_type: dict[str, int] = {}
    for alert in active:
        by_type[alert.type] = by_type.get(alert.type, 0) + 1
    return AlertSummary(
        active=len(active),
        critical=sum(1 for a in active if a.severity == "critical"),
        warning=sum(1 for a in active if a.severity == "warning"),
        unacknowledged=sum(1 for a in active if not a.acknowledged),
        by_type=by_type,
    )


@router.get("/{alert_id}", response_model=Alert)
async def get_alert(alert_id: str, store: AlertStore = Depends(get_alert_store)) -> Alert:
    alert = await store.get_alert(alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id!r} not found")
    return alert


@router.post("/{alert_id}/acknowledge", response_model=Alert)
async def acknowledge(alert_id: str, store: AlertStore = Depends(get_alert_store)) -> Alert:
    """Mark an alert as seen. It still resolves by itself when the condition clears."""
    alert = await store.get_alert(alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id!r} not found")
    if not alert.acknowledged:
        await store.update_alert(alert_id, {"acknowledged": True, "acknowledged_at": datetime.now(timezone.utc)})
    return await store.get_alert(alert_id)
