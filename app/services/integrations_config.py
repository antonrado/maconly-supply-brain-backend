from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import WbIntegrationAccount, MoySkladIntegrationAccount
from app.schemas.integrations import (
    IntegrationsConfigSnapshot,
    MoySkladAccountInfo,
    WbAccountInfo,
)


def build_integrations_config_snapshot(db: Session) -> IntegrationsConfigSnapshot:
    wb_rows = db.query(WbIntegrationAccount).order_by(WbIntegrationAccount.id).all()
    ms_rows = db.query(MoySkladIntegrationAccount).order_by(MoySkladIntegrationAccount.id).all()

    wb_accounts = [
        WbAccountInfo(
            id=row.id,
            name=row.name,
            supplier_id=row.supplier_id,
            is_active=row.is_active,
        )
        for row in wb_rows
    ]

    moysklad_accounts = [
        MoySkladAccountInfo(
            id=row.id,
            name=row.name,
            account_id=row.account_id,
            is_active=row.is_active,
        )
        for row in ms_rows
    ]

    return IntegrationsConfigSnapshot(
        wb_accounts=wb_accounts,
        moysklad_accounts=moysklad_accounts,
    )
