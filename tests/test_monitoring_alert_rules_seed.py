from __future__ import annotations

from app.models.models import MonitoringAlertRule
from app.schemas.monitoring_alerts import AlertRuleCreate
from app.services.monitoring_alert_rules_seed import seed_monitoring_alert_rules


def test_seed_monitoring_alert_rules_empty_db(db_session):
    created, skipped = seed_monitoring_alert_rules(db_session)

    assert len(created) == 9
    assert skipped == []

    rules = db_session.query(MonitoringAlertRule).all()
    assert len(rules) == 9


def test_seed_monitoring_alert_rules_idempotent(db_session):
    created_first, skipped_first = seed_monitoring_alert_rules(db_session)
    assert len(created_first) == 9
    assert skipped_first == []

    created_second, skipped_second = seed_monitoring_alert_rules(db_session)
    assert created_second == []
    assert len(skipped_second) == 9

    rules = db_session.query(MonitoringAlertRule).all()
    assert len(rules) == 9


def test_seed_monitoring_alert_rules_partial_match(db_session):
    # Pre-create rule #3 ("Нет активных WB аккаунтов") with the same fields
    payload = AlertRuleCreate(
        name="Нет активных WB аккаунтов",
        metric="wb_accounts_active",
        threshold_type="below",
        threshold_value=1,
        severity="critical",
        is_active=True,
    )

    existing_rule = MonitoringAlertRule(
        name=payload.name,
        metric=payload.metric,
        threshold_type=payload.threshold_type,
        threshold_value=payload.threshold_value,
        severity=payload.severity,
        is_active=payload.is_active,
    )
    db_session.add(existing_rule)
    db_session.commit()
    db_session.refresh(existing_rule)

    created, skipped = seed_monitoring_alert_rules(db_session)

    assert len(created) == 8
    assert len(skipped) == 1
    assert existing_rule.id in skipped

    rules = db_session.query(MonitoringAlertRule).all()
    assert len(rules) == 9
