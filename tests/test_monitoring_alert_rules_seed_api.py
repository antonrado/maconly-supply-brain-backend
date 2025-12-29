from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import MonitoringAlertRule
from app.services import monitoring_alert_rules_seed


@pytest.fixture
def client(db_session):
    def _get_db_override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_alert_rules_seed_initial_empty_db(client, db_session):
    # S1: первичный сидинг в пустую БД
    assert db_session.query(MonitoringAlertRule).count() == 0

    resp = client.post("/api/v1/planning/monitoring/alert-rules/seed")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    expected_count = len(monitoring_alert_rules_seed.RULES)

    assert len(body["created_ids"]) == expected_count
    assert body["skipped_ids"] == []

    total = db_session.query(MonitoringAlertRule).count()
    assert total == expected_count


def test_alert_rules_seed_idempotent_second_call(client, db_session):
    # S2: повторный вызов — все правила уходят в skipped_ids
    resp1 = client.post("/api/v1/planning/monitoring/alert-rules/seed")
    assert resp1.status_code == 200, resp1.text
    body1 = resp1.json()

    first_created = set(body1["created_ids"])
    total_after_first = db_session.query(MonitoringAlertRule).count()

    resp2 = client.post("/api/v1/planning/monitoring/alert-rules/seed")
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()

    assert body2["created_ids"] == []
    assert set(body2["skipped_ids"]) == first_created

    total_after_second = db_session.query(MonitoringAlertRule).count()
    assert total_after_second == total_after_first


def test_alert_rules_seed_partially_prefilled_db(client, db_session):
    # S3: частично предзаполненная БД
    base_rule = monitoring_alert_rules_seed.RULES[0]

    # Создаём правило, совпадающее по ключевым полям с одним из базовых
    existing_rule = MonitoringAlertRule(
        name=base_rule["name"],
        metric=base_rule["metric"],
        threshold_type=base_rule["threshold_type"],
        threshold_value=base_rule["threshold_value"],
        severity=base_rule["severity"],
        is_active=base_rule["is_active"],
    )
    db_session.add(existing_rule)
    db_session.commit()

    resp = client.post("/api/v1/planning/monitoring/alert-rules/seed")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    expected_count = len(monitoring_alert_rules_seed.RULES)

    # В skipped_ids должен быть id уже существующего правила
    assert existing_rule.id in body["skipped_ids"]

    total = db_session.query(MonitoringAlertRule).count()
    assert total == expected_count

    # created_ids + skipped_ids по длине дают полный базовый набор
    assert len(body["created_ids"]) + len(body["skipped_ids"]) == expected_count
