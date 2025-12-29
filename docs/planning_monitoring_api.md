# Planning & Monitoring API Overview

Этот документ описывает основные HTTP-эндпоинты ядра планирования и мониторинга закупок: блоки **Planning & Bundles** и **Monitoring & Alerts Hub** под общим префиксом `/api/v1/planning`.

## Endpoint summary

| Block               | Method | Path                                          | Short description                                      |
|---------------------|--------|-----------------------------------------------|--------------------------------------------------------|
| Planning & Bundles  | GET    | /api/v1/planning/integrations/config-snapshot | Snapshot of configured WB/MoySklad integration accounts |
| Planning & Bundles  | GET    | /api/v1/planning/demand                       | Demand metrics per article                             |
| Planning & Bundles  | GET    | /api/v1/planning/bundle-availability          | Bundle availability for a specific article/type/warehouse |
| Planning & Bundles  | GET    | /api/v1/planning/article-bundle-snapshot      | Detailed bundle & inventory snapshot for an article    |
| Planning & Bundles  | GET    | /api/v1/planning/bundle-risk-portfolio        | Bundle risk portfolio across articles                  |
| Planning & Bundles  | GET    | /api/v1/planning/order-explanation-portfolio  | Purchase proposal explanation portfolio per article    |
| Planning & Bundles  | GET    | /api/v1/planning/health-portfolio             | Combined planning health portfolio per article         |
| Planning & Bundles  | GET    | /api/v1/planning/article-dashboard/{article_id} | Drilldown dashboard for a single article             |
| Planning & Bundles  | GET    | /api/v1/planning/config-snapshot              | Snapshot of planning settings configuration            |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/snapshot          | On-the-fly monitoring snapshot                         |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/metrics           | Catalog of monitoring metrics and their capabilities   |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/layout           | Layout-конфиг мониторингового дашборда                |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/bootstrap        | UI bootstrap: metrics + layout + status               |
| Monitoring & Alerts | POST   | /api/v1/planning/monitoring/snapshot/capture  | Capture and persist current monitoring snapshot        |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/history           | History of persisted monitoring snapshots              |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/alerts            | Currently active monitoring alerts                     |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/alert-rules       | List of monitoring alert rules                         |
| Monitoring & Alerts | POST   | /api/v1/planning/monitoring/alert-rules       | Create a new monitoring alert rule                     |
| Monitoring & Alerts | PATCH  | /api/v1/planning/monitoring/alert-rules/{id}  | Update an existing monitoring alert rule               |
| Monitoring & Alerts | DELETE | /api/v1/planning/monitoring/alert-rules/{id}  | Delete an existing monitoring alert rule               |
| Monitoring & Alerts | POST   | /api/v1/planning/monitoring/alert-rules/seed  | Seed default monitoring alert rules (admin)            |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/dashboard         | Aggregated monitoring dashboard                        |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/status            | Lightweight monitoring status (traffic light + counts) |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/timeseries        | Timeseries for selected monitoring metrics             |
| Monitoring & Alerts | GET    | /api/v1/planning/monitoring/risk-focus        | Top risky articles/bundles by bundle risk model        |

---

## Planning & Bundles

### GET /api/v1/planning/integrations/config-snapshot

**Назначение:** вернуть снимок конфигурации интеграций (WB и MoySklad) для использования в планировании и мониторинге.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/integrations/config-snapshot`
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK`
- Тело: [`IntegrationsConfigSnapshot`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/integrations.py:0:0-0:0)
- Ключевые поля:
  - список WB-аккаунтов и MoySklad-аккаунтов с `id`, человекочитаемым именем и флагом активности.

**Примечания:**
- Не возвращает чувствительные данные (API-токены), только метаданные аккаунтов.

---

### GET /api/v1/planning/demand

**Назначение:** расчёт спроса и дефицита по одному артикулу на заданную дату.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/demand`
- Параметры:
  - `article_id: int` — идентификатор артикула.
  - `target_date: date` — целевая дата (формат ISO `YYYY-MM-DD`).

**Ответ:**
- Статус: `200 OK`
- Тело: [`DemandResult`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/demand.py:0:0-0:0)
- Ключевые поля:
  - рассчитанный дефицит и прогнозируемый спрос по артикулу.

**Примечания:**
- Используется как основа для формирования предложений по закупкам.

---

### GET /api/v1/planning/bundle-availability

**Назначение:** расчёт доступных бандлов для конкретного артикула, типа бандла и склада.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/bundle-availability`
- Параметры:
  - `article_id: int` — идентификатор артикула.
  - `bundle_type_id: int` — тип бандла.
  - `warehouse_id: int` — склад.

**Ответ:**
- Статус: `200 OK`
- Тело: [`BundleAvailabilityResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/planning.py:0:0-0:0)
- Ключевые поля:
  - количество доступных бандлов и ограничения по складу/остаткам.

**Примечания:**
- Использует существующую логику bundle planning и учёт остатков NSC/WB.

---

### GET /api/v1/planning/article-bundle-snapshot

**Назначение:** подробный снимок запасов и бандлов для одного артикула (NSC + WB).

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/article-bundle-snapshot`
- Параметры:
  - `article_id: int` — идентификатор артикула.

**Ответ:**
- Статус: `200 OK`
- Тело: [`ArticleInventorySnapshot`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/article_bundle_snapshot.py:0:0-0:0)
- Ключевые поля:
  - структура по остаткам NSC (singles), остаткам WB (bundles) и потенциальным бандлам.

**Примечания:**
- Используется как базовый слой для риск-модели бандлов и health-портфеля.

---

### GET /api/v1/planning/bundle-risk-portfolio

**Назначение:** портфель рисков по бандлам для набора артикулов или всех активных.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/bundle-risk-portfolio`
- Параметры:
  - `article_ids: list[int] | None` — опциональный список артикулов (`?article_ids=1&article_ids=2`). Если не задан — используются все активные.

**Ответ:**
- Статус: `200 OK`
- Тело: [`BundleRiskPortfolioResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/bundle_risk.py:0:0-0:0)
- Ключевые поля:
  - список `ArticleBundleRiskEntry` c `risk_level`, `days_of_cover`, `total_available_bundles` и текстовой `explanation`.

**Примечания:**
- Риск-модель переиспользуется другими сервисами (health-портфель, monitoring risk-focus).

---

### GET /api/v1/planning/order-explanation-portfolio

**Назначение:** портфель объяснений по предложениям закупок, сгруппированный по артикулам.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/order-explanation-portfolio`
- Параметры:
  - `article_ids: list[int] | None` — опциональный список артикулов. Если не задан — используются все активные.

**Ответ:**
- Статус: `200 OK`
- Тело: [`OrderExplanationPortfolioResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/order_explanation.py:0:0-0:0)
- Ключевые поля:
  - список `ArticleOrderExplanation` с массивом `OrderProposalReason` (обоснование `final_order_qty`).

**Примечания:**
- Переиспользует те же расчёты, что и сервис формирования заказов (`generate_order_proposal`).

---

### GET /api/v1/planning/health-portfolio

**Назначение:** сводный health-портфель по артикулу, объединяющий bundle-risk и order-explanation.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/health-portfolio`
- Параметры:
  - `article_ids: list[int] | None` — опциональный список артикулов.

**Ответ:**
- Статус: `200 OK`
- Тело: [`PlanningHealthPortfolioResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/planning_health.py:0:0-0:0)
- Ключевые поля:
  - `ArticleHealthSummary` с худшим `risk_level`, days_of_cover и агрегированным `total_final_order_qty`.

**Примечания:**
- Удобен для сводных дашбордов планирования и приоритизации артикулов.

---

### GET /api/v1/planning/article-dashboard/{article_id}

**Назначение:** дашборд по одной статье/бандлу: риск, объяснение заказа и health-информация.

**Запрос:**
- Метод: `GET` 
- Путь: `/api/v1/planning/article-dashboard/{article_id}` 
- Параметры:
  - `article_id: int` (path, required)

**Ответ:**
- Статус: `200 OK` или `404 Not Found` 
- Тело: [`ArticleDashboardResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/article_dashboard.py:0:0-0:0)

**Примечания:**
- Использует существующие портфели: bundle risk, order explanation, planning health.
- Если статья не присутствует ни в одном портфеле, возвращается `404`.

---

### GET /api/v1/planning/config-snapshot

**Назначение:** снимок настроек планирования (глобальные и по статьям), используемых в расчётах спроса и заказов.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/config-snapshot`
- Параметры:
  - `article_id: int | None` — опциональный ID артикула; при указании возвращается конфигурация только для него.

**Ответ:**
- Статус: `200 OK`
- Тело: [`PlanningConfigSnapshotResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/planning_settings.py:0:0-0:0)
- Ключевые поля:
  - `global_settings` и перечень article-level настроек (порог, safety stock, минимальные партии и т.п.).

**Примечания:**
- Только read-only снапшот, не предназначен для редактирования настроек.

---

## Monitoring & Alerts Hub

### GET /api/v1/planning/monitoring/metrics

**Назначение:** справочник по поддерживаемым метрикам мониторинга (для UI дашборда, alert-правил и графиков).

**Запрос:**
- Метод: `GET` 
- Путь: `/api/v1/planning/monitoring/metrics` 
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK` 
- Тело: [[MonitoringMetricsResponse](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_metrics.py:0:0-0:0)](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_metrics.py:0:0-0:0)

**Примечания:**
- Каждая метрика описана полями `metric`, `category`, `label`, `description`.
- Флаги `supports_alerts`, `supports_timeseries`, `used_in_status` помогают фронтенду решать, где метрику можно использовать (правила, графики, светофор статуса).

### GET /api/v1/planning/monitoring/layout

**Назначение:** вернуть статичный конфиг layout мониторингового дашборда (секции и тайлы), который используется фронтендом.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/layout`
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringLayoutResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_layout.py:0:0-0:0)

**Примечания:**
- Конфигурация статична и не ходит в БД.
- Описывает структуру секций (`id`, `title`, `description`) и тайлов (`id`, `title`, `description`, `type`, `primary_metric`, `secondary_metrics`, `source_endpoint`, `source_params`).
- Значения `primary_metric` и `secondary_metrics` должны совпадать с каталогом метрик `/monitoring/metrics` (см. `MonitoringMetricsResponse`), в том числе с учётом timeseries-метрик.
- Используется фронтендом как единый источник правды о структуре мониторингового дашборда.

### GET /api/v1/planning/monitoring/bootstrap

**Назначение:** единый эндпоинт для инициализации monitoring-дэшборда на фронте (метрики, layout, статус).

**Запрос:**
- Метод: `GET` 
- Путь: `/api/v1/planning/monitoring/bootstrap` 
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK` 
- Тело: [`MonitoringBootstrapResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_bootstrap.py:0:0-0:0)

**Примечания:**
- Оборачивает существующие сервисы: каталог метрик, layout и статус.
- Статус (`status` в ответе) вычисляется теми же сервисами, что и для `/monitoring/status` и `/monitoring/dashboard` (см. `build_monitoring_status`).
- Эндпоинт требует доступа к БД через стандартную зависимость `get_db` (как и `/monitoring/status`).
- Метрики и layout в bootstrap строго согласованы с `/monitoring/metrics` и `/monitoring/layout` (см. соответствующие тесты на консистентность).

### GET /api/v1/planning/monitoring/snapshot

**Назначение:** собрать on-the-fly `MonitoringSnapshot` по ключевым сигналам (интеграции, риски, заказы).

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/snapshot`
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringSnapshot`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring.py:0:0-0:0)
- Ключевые поля:
  - `integrations`, `risks`, `orders`, `updated_at`.

**Примечания:**
- Не сохраняет данные в историю, используется для актуального состояния.

---

### POST /api/v1/planning/monitoring/snapshot/capture

**Назначение:** построить текущий `MonitoringSnapshot`, сохранить его в БД как `MonitoringSnapshotRecord` и вернуть сохранённую запись.

**Запрос:**
- Метод: `POST`
- Путь: `/api/v1/planning/monitoring/snapshot/capture`
- Параметры: отсутствуют
- Тело запроса: отсутствует

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringSnapshotRecordSchema`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_history.py:0:0-0:0)
- Ключевые поля:
  - значения метрик снапшота и `created_at`.

**Примечания:**
- Предполагается вызывать по расписанию (cron) для накопления истории мониторинга.

---

### GET /api/v1/planning/monitoring/history

**Назначение:** вернуть историю сохранённых мониторинговых снапшотов.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/history`
- Параметры:
  - `limit: int` — по умолчанию `30`, диапазон `[1, 365]`.

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringHistoryResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_history.py:0:0-0:0)
- Ключевые поля:
  - список `MonitoringSnapshotRecordSchema` в порядке от новых к старым.

**Примечания:**
- Используется как источник для графиков и аналитики.

---

### GET /api/v1/planning/monitoring/alerts

**Назначение:** вернуть список текущих сработавших алертов по правилам мониторинга.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/alerts`
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK`
- Тело: [`ActiveAlertsResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alerts.py:0:0-0:0)
- Ключевые поля:
  - `items` — список алертов с `metric`, `severity`, `current_value`, `threshold_type`, `threshold_value`.

**Примечания:**
- Использует те же данные, что и monitoring history/snapshot: при наличии истории предпочитает последнюю запись, иначе строит on-the-fly снапшот.

---

### GET /api/v1/planning/monitoring/alert-rules

**Назначение:** получить список всех правил мониторинга.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/alert-rules`
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK`
- Тело: [`AlertRuleListResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alerts.py:0:0-0:0)
- Ключевые поля:
  - список `AlertRuleSchema` с `metric`, `threshold_type`, `threshold_value`, `severity`, `is_active`.

---

### POST /api/v1/planning/monitoring/alert-rules

**Назначение:** создать новое правило мониторинга.

**Запрос:**
- Метод: `POST`
- Путь: `/api/v1/planning/monitoring/alert-rules`
- Параметры: отсутствуют
- Тело запроса: [`AlertRuleCreate`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alerts.py:0:0-0:0)

**Ответ:**
- Статус: `200 OK`
- Тело: [`AlertRuleSchema`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alerts.py:0:0-0:0)

**Примечания:**
- Валидирует `metric`, `threshold_type` (`above`/`below`), `severity` (`warning`/`critical`) и неотрицательный `threshold_value`.

---

### PATCH /api/v1/planning/monitoring/alert-rules/{rule_id}

**Назначение:** частично обновить существующее правило мониторинга.

**Запрос:**
- Метод: `PATCH`
- Путь: `/api/v1/planning/monitoring/alert-rules/{rule_id}`
- Параметры пути:
  - `rule_id: int` — идентификатор правила.
- Тело запроса: [`AlertRuleUpdate`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alerts.py:0:0-0:0)

**Ответ:**
- Статус: `200 OK` (успех) или `404 Not Found` (если правило не найдено)
- Тело: [`AlertRuleSchema`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alerts.py:0:0-0:0)

---

### DELETE /api/v1/planning/monitoring/alert-rules/{rule_id}

**Назначение:** удалить существующее правило мониторинга.

**Запрос:**
- Метод: `DELETE`
- Путь: `/api/v1/planning/monitoring/alert-rules/{rule_id}`
- Параметры пути:
  - `rule_id: int` — идентификатор правила.

**Ответ:**
- Статус: `204 No Content` (успешное удаление) или `404 Not Found` (если правило не найдено)
- Тело: отсутствует

---

### POST /api/v1/planning/monitoring/alert-rules/seed

**Назначение:** админский эндпоинт для первичного/повторного сидинга базового набора правил мониторинга.

**Запрос:**
- Метод: `POST` 
- Путь: `/api/v1/planning/monitoring/alert-rules/seed` 
- Параметры: отсутствуют
- Тело: пустое

**Ответ:**
- Статус: `200 OK` 
- Тело: [`MonitoringAlertRulesSeedResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alert_rules_seed.py:0:0-0:0)

**Примечания:**
- Использует внутренний сидер `seed_monitoring_alert_rules`.
- При первом запуске создаёт базовый набор правил, их ID попадают в `created_ids`.
- При повторных запусках уже существующие правила попадают в `skipped_ids`, новые не создаются (идемпотентное поведение).

---

### GET /api/v1/planning/monitoring/dashboard

**Назначение:** агрегированный дашборд мониторинга, собирающий несколько источников в один ответ.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/dashboard`
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringDashboardResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_dashboard.py:0:0-0:0)
- Ключевые поля:
  - `snapshot` (`MonitoringSnapshot`), `history` (`MonitoringHistoryResponse`), `alerts` (`ActiveAlertsResponse`), `rules` (`AlertRuleListResponse`), `status` (`MonitoringStatusSummary`).

**Примечания:**
- `status` вычисляется общей функцией статуса (см. `/monitoring/status`) и показывает светофор + количество алертов по уровням.

---

### GET /api/v1/planning/monitoring/status

**Назначение:** лёгкий эндпоинт статуса мониторинга для светофора и простых health-чеков.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/status`
- Параметры: отсутствуют

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringStatusResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_dashboard.py:0:0-0:0)
- Ключевые поля:
  - `overall_status` (`"ok"` / `"warning"` / `"critical"`), `critical_alerts`, `warning_alerts`, `updated_at`.

**Примечания:**
- Использует общий движок статуса, который применяет детерминированное правило приоритета:
  - при наличии хотя бы одного активного `critical`-алерта статус `overall_status == "critical"`;
  - иначе при наличии хотя бы одного активного `warning`-алерта статус `overall_status == "warning"`;
  - иначе при наличии проблем в snapshot (например, `risk_critical > 0` или `wb_accounts_active == 0` или `ms_accounts_active == 0`) статус `overall_status == "warning"`;
  - иначе статус `overall_status == "ok"`.

---

### GET /api/v1/planning/monitoring/timeseries

**Назначение:** вернуть готовые временные ряды по выбранным метрикам мониторинга на основе `MonitoringSnapshotRecord`.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/timeseries`
- Параметры:
  - `metrics: list[str]` — **обязательный** список метрик (`?metrics=risk_critical&metrics=wb_accounts_active`).
  - `limit: int` — по умолчанию `30`, диапазон `[1, 365]`.

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringTimeseriesResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_timeseries.py:0:0-0:0)
- Ключевые поля:
  - `items` — список `MonitoringMetricSeries`, каждая c `metric` и массивом точек (`timestamp`, `value`).

**Примечания:**
- Если `metrics` не передан вовсе, возвращается `400 Bad Request` с detail о том, что параметр обязателен.
- Используются не более `limit` последних снапшотов; внутри каждой серии точки отсортированы по времени (от старых к новым).
- Если истории нет (нет ни одной записи), возвращается `items == []`.

---

### GET /api/v1/planning/monitoring/risk-focus

**Назначение:** вернуть топ самых проблемных артикулов/бандлов по рискам для отображения "листа смерти" на дашборде.

**Запрос:**
- Метод: `GET`
- Путь: `/api/v1/planning/monitoring/risk-focus`
- Параметры:
  - `limit: int` — по умолчанию `20`, диапазон `[1, 100]`.

**Ответ:**
- Статус: `200 OK`
- Тело: [`MonitoringTopRiskResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_risk_focus.py:0:0-0:0)
- Ключевые поля:
  - `items` — список `MonitoringTopRiskItem` с `article_id`, `article_code`, `bundle_type_id`, `bundle_type_name`, `risk_level`, `days_of_cover`.

**Примечания:**
- Использует существующий портфель рисков (`build_bundle_risk_portfolio`) без пересчёта логики.
- Сортировка по уровню риска (например, `critical` → `warning` → `no_data` → `ok` → `overstock`), затем по стабильным идентификаторам (article_id/bundle_type) для детерминированного порядка.
- Если портфель пустой, возвращается `items == []`.
