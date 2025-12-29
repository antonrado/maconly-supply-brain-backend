from __future__ import annotations

from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models.models import MonitoringAlertRule
from app.schemas.monitoring_alerts import AlertRuleCreate
from app.services.monitoring_metrics import get_alert_rule_metrics


RULES = [
    {
        "name": "Есть критические риски",
        "metric": "risk_critical",
        "threshold_type": "above",
        "threshold_value": 0,
        "severity": "critical",
        "is_active": True,
    },
    {
        "name": "Слишком много warning",
        "metric": "risk_warning",
        "threshold_type": "above",
        "threshold_value": 5,
        "severity": "warning",
        "is_active": True,
    },
    {
        "name": "Нет активных WB аккаунтов",
        "metric": "wb_accounts_active",
        "threshold_type": "below",
        "threshold_value": 1,
        "severity": "critical",
        "is_active": True,
    },
    {
        "name": "Нет активных MS аккаунтов",
        "metric": "ms_accounts_active",
        "threshold_type": "below",
        "threshold_value": 1,
        "severity": "critical",
        "is_active": True,
    },
    {
        "name": "Нет статей с финальным заказом",
        "metric": "articles_with_orders",
        "threshold_type": "below",
        "threshold_value": 1,
        "severity": "warning",
        "is_active": True,
    },
    {
        "name": "Итоговый заказ отсутствует",
        "metric": "total_final_order_qty",
        "threshold_type": "below",
        "threshold_value": 1,
        "severity": "critical",
        "is_active": True,
    },
    {
        "name": "Слишком много overstock",
        "metric": "risk_overstock",
        "threshold_type": "above",
        "threshold_value": 10,
        "severity": "warning",
        "is_active": True,
    },
    {
        "name": "Много статей без данных",
        "metric": "risk_no_data",
        "threshold_type": "above",
        "threshold_value": 3,
        "severity": "warning",
        "is_active": True,
    },
    {
        "name": "Подозрительно всё хорошо",
        "metric": "risk_ok",
        "threshold_type": "below",
        "threshold_value": 1,
        "severity": "warning",
        "is_active": False,
    },
]


def seed_monitoring_alert_rules(db: Session) -> Tuple[List[int], List[int]]:
    """Create baseline monitoring alert rules if they do not exist.

    Returns (created_rule_ids, skipped_rule_ids).
    """

    created_ids: List[int] = []
    skipped_ids: List[int] = []

    allowed_metrics = get_alert_rule_metrics()
    for data in RULES:
        assert data["metric"] in allowed_metrics, f"Seed rule metric {data['metric']} is not in monitoring metrics catalog"

        payload = AlertRuleCreate(**data)

        existing = (
            db.query(MonitoringAlertRule)
            .filter_by(
                name=payload.name,
                metric=payload.metric,
                threshold_type=payload.threshold_type,
                threshold_value=payload.threshold_value,
                severity=payload.severity,
                is_active=payload.is_active,
            )
            .first()
        )
        if existing is not None:
            skipped_ids.append(existing.id)
            continue

        rule = MonitoringAlertRule(
            name=payload.name,
            metric=payload.metric,
            threshold_type=payload.threshold_type,
            threshold_value=payload.threshold_value,
            severity=payload.severity,
            is_active=payload.is_active,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        created_ids.append(rule.id)

    return created_ids, skipped_ids
