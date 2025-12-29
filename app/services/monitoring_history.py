from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import MonitoringSnapshotRecord
from app.schemas.monitoring_history import MonitoringSnapshotRecordSchema
from app.services.monitoring import build_monitoring_snapshot


def build_and_persist_monitoring_snapshot(db: Session) -> MonitoringSnapshotRecordSchema:
    snapshot = build_monitoring_snapshot(db=db)

    record = MonitoringSnapshotRecord(
        wb_accounts_total=snapshot.integrations.wb_accounts_total,
        wb_accounts_active=snapshot.integrations.wb_accounts_active,
        ms_accounts_total=snapshot.integrations.ms_accounts_total,
        ms_accounts_active=snapshot.integrations.ms_accounts_active,
        risk_critical=snapshot.risks.critical,
        risk_warning=snapshot.risks.warning,
        risk_ok=snapshot.risks.ok,
        risk_overstock=snapshot.risks.overstock,
        risk_no_data=snapshot.risks.no_data,
        articles_with_orders=snapshot.orders.articles_with_orders,
        total_final_order_qty=snapshot.orders.total_final_order_qty,
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return MonitoringSnapshotRecordSchema.model_validate(record, from_attributes=True)


def get_monitoring_history(db: Session, limit: int = 30) -> list[MonitoringSnapshotRecordSchema]:
    rows = (
        db.query(MonitoringSnapshotRecord)
        .order_by(MonitoringSnapshotRecord.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        MonitoringSnapshotRecordSchema.model_validate(row, from_attributes=True)
        for row in rows
    ]
