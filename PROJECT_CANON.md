# PROJECT_CANON – Maconly Supply Brain Backend

## 1. Project Overview

- **Project name**: Maconly Supply Brain – Backend
- **Purpose**: Backend-сервис для внутренней системы Maconly Supply Brain. Предоставляет HTTP API для получения мониторинговых метрик состояния планирования, работы интеграций и связанных рисков, хранит эти данные в PostgreSQL и обеспечивает их историзацию.

- **What the system DOES**
  - Экспортирует REST API (FastAPI) под префиксом `/api/v1`, в том числе подмодуль `planning/monitoring`.
  - Использует PostgreSQL как единственный источник правды для прикладного состояния.
  - Строит агрегированные мониторинговые снапшоты и сохраняет их в таблицу `monitoring_snapshots`.
  - Предоставляет текущее состояние, историю и временные ряды мониторинговых метрик через API.

- **What the system does NOT do**
  - Не содержит фронтенд/UI-код — данный репозиторий описывает только backend.
  - Не управляет внешней инфраструктурой (оркестрация, деплой, и т.п.) за пределами Docker Compose-конфигурации для локальной/разработческой среды.

---

## 2. Core Principles (immutable)

- **Empty state = valid state**  
  Отсутствие данных (пустые таблицы, отсутствие снапшотов) не считается ошибкой. Эндпоинты мониторинга обязаны возвращать корректные ответы (HTTP 200 и валидный JSON) даже при пустом состоянии БД.

- **Backend-first**  
  Вся доменная логика (агрегации, правила, вычисление метрик) живёт на backend-е. Клиенты не должны дублировать бизнес-логику и работают поверх стабильного API.

- **No try/except instead of schema**  
  Ошибки целостности схемы (отсутствующие таблицы, поля и т.п.) устраняются через Alembic-миграции и корректные SQLAlchemy-модели, а не через `try/except` вокруг обращений к БД. Поведение системы должно быть детерминированным при согласованной схеме.

- **Explainability**  
  Метрики и статус мониторинга должны быть объяснимы через API и логи: какие интеграции активны, какие риски посчитаны, какие заказы попали в расчёт. Логика агрегации инкапсулирована в сервисах (`app/services/*`) и не скрыта в «магии» на уровне БД.

- **Scheduler ≠ API**  
  Планировщик не содержит собственной бизнес-логики. Он только оркестрирует периодический вызов тех же сервисных функций, которые используются HTTP-эндпоинтами (например, `build_and_persist_monitoring_snapshot`), и разделён по слоям от FastAPI-роутинга.

---

## 3. Architecture Overview

- **Backend stack**
  - FastAPI — HTTP API и маршрутизация (`app/main.py`, `app/api/v1/*`).
  - SQLAlchemy — ORM-модели и доступ к БД (`app/models/models.py`).
  - PostgreSQL — основная БД (контейнер `db` в `docker-compose.yml`).
  - Alembic — управление схемой БД через миграции (`alembic/versions/*.py`).
  - APScheduler — фоновый планировщик для периодических задач (`app/services/monitoring_scheduler.py`).
  - Docker / Docker Compose — локальная/разработческая среда (`docker-compose.yml`).

- **Высокоуровневое взаимодействие модулей**
  - HTTP-запросы приходят в FastAPI-приложение, описанное в `app/main.py`.
  - Роутеры в `app/api/v1/*` вызывают функции сервисного слоя в `app/services/*`.
  - Сервисы работают с SQLAlchemy-моделями из `app/models/models.py` через `SessionLocal` из `app/core/db.py`.
  - Alembic-миграции гарантируют, что структура БД соответствует моделям.
  - Логи фиксируют ключевые события (старты/остановки планировщика, выполнение задач, исключения).

- **Где живёт scheduler и как запускается**
  - Реализация планировщика: `app/services/monitoring_scheduler.py` (класс `MonitoringScheduler`).
  - Инициализация и жизненный цикл:
    - В `app/main.py` в обработчике события `startup` создаётся и запускается экземпляр `MonitoringScheduler` с интервалом 15 минут и сохраняется в `app.state.monitoring_scheduler`.
    - В обработчике события `shutdown` планировщик извлекается из `app.state` и корректно останавливается.
  - Планировщик использует APScheduler `BackgroundScheduler` и задачу, вызывающую `build_and_persist_monitoring_snapshot(db)` из `app/services/monitoring_history.py` с отдельной DB-сессией (`SessionLocal`).

---

## 4. Implemented Modules (COMPLETED)

### 4.1 Monitoring v1 — STABLE

- **Tables (ключевые для Monitoring v1)**
  - `monitoring_snapshots` — исторические агрегированные метрики (интеграции, риски, заказы, `created_at`).
  - `monitoring_alert_rules` — правила оповещений по мониторинговым метрикам.
  - Интеграционные таблицы, от которых зависят метрики мониторинга:
    - `wb_integration_accounts`
    - `moysklad_integration_accounts`

- **Endpoints** (под префиксом `/api/v1/planning/monitoring`)
  - `GET /bootstrap` — агрегированная стартовая информация для фронта (bootstrap мониторинга).
  - `GET /status` — текущее состояние мониторинга на основе последнего снапшота.
  - `GET /snapshot` — построение и возврат одного актуального снапшота (без записи в историю либо с записью, в зависимости от реализованной логики сервиса).
  - `GET /history` — список последних сохранённых снапшотов (`MonitoringSnapshotRecord`) с ограничением по `limit`.
  - `GET /timeseries` — временные ряды по выбранным метрикам на основе `monitoring_snapshots`.

- **Scheduler**
  - Реализован в `app/services/monitoring_scheduler.py` и интегрирован в `app/main.py`.
  - Использует APScheduler `BackgroundScheduler` с интервалом 15 минут.
  - Задача:
    - Создаёт DB-сессию через `SessionLocal`.
    - Вызывает `build_and_persist_monitoring_snapshot(db)` из `app/services/monitoring_history.py`.
    - Логирует старт/успех/исключения; при ошибке не останавливает приложение.
  - Поведение multi-instance:
    - Advisory lock реализован через PostgreSQL (`pg_try_advisory_lock` / `pg_advisory_unlock`) на выделенном соединении.
    - E2E-проверка проведена с двумя backend-сервисами (`backend` и `backend2`) в `docker-compose.yml`, работающими против одной БД: только один из них получает lock и запускает планировщик, второй логирует, что lock не получен и не создаёт снапшоты.

- **Текущий статус: STABLE**
  - Alembic-миграции применены вплоть до `0008_add_monitoring_alert_rules.py`.
  - Таблицы `monitoring_snapshots` и `monitoring_alert_rules` существуют и используются сервисами.
  - Эндпоинты `/status`, `/bootstrap`, `/snapshot`, `/history`, `/timeseries` отдают HTTP 200 и валидный JSON при актуальном состоянии схемы.
  - Планировщик успешно создаёт периодические записи в `monitoring_snapshots` (подтверждено через `SELECT count(*) FROM monitoring_snapshots;`).

### 4.2 Planning Core v1 — Skeleton

- **Purpose**
  - Подготовить минимальный каркас для будущего ядра планирования (Planning Core v1), не влияя на существующую функциональность мониторинга.

- **What is implemented now**
  - Модуль `app/core/planning/domain.py` с минимальными датаклассами:
    - `PlanningSettings`
    - `DemandInput`
    - `SupplyInput`
    - `OrderProposal`
    - `PlanningHealth`
  - Модуль `app/core/planning/service.py` с классом `PlanningService` и методами, которые пока что всегда поднимают `NotImplementedError`:
    - `compute_order_proposal(...)`
    - `get_planning_health(...)`
  - HTTP-эндпоинты (скелет) в `app/api/v1/endpoints/planning_core.py` и роутинг в `app/api/v1/router.py`:
    - `GET  /api/v1/planning/core/health`
    - `POST /api/v1/planning/core/proposal`

- **Explicitly NOT implemented yet**
  - **Нет** бизнес-логики планирования, **нет** вычислений заказов и спроса.
  - **Нет** новых таблиц БД и **нет** Alembic-миграций для Planning Core.
  - Эндпоинты Planning Core v1 **намеренно** возвращают HTTP 501 Not Implemented c телом `{ "detail": "Not Implemented" }`.

---

## 5. Active Stage

- **Stage name**: Planning Core v1
- **Goal**: сформировать и зафиксировать в backend-е первую версию ядра планирования (модели, сервисы, API), на которое будут опираться остальные модули.
- **Status**: SKELETON ONLY  
  На текущем этапе создан только скелет (структура модулей и HTTP-эндпоинтов). Бизнес-логика планирования и взаимодействие с БД ещё не реализованы.

---

## 6. Open Questions / Risks

- **Multi-instance scheduler (mitigated via PostgreSQL advisory lock)**
  - Планировщик использует глобальный PostgreSQL advisory lock с фиксированным BIGINT-ключом, чтобы только один backend-процесс мог запустить APScheduler и выполнять job.
  - При запуске нескольких экземпляров backend-а только тот процесс, который успешно получил lock, запускает планировщик; остальные логируют, что lock не получен, и не создают снапшоты.
  - Остаточный риск связан с зависимостью от доступности БД и отсутствием внешнего оркестратора роли «лидера» при более сложном масштабировании.

- **Scaling**
  - Архитектура сейчас ориентирована на один backend-инстанс и один экземпляр PostgreSQL.
  - Нет отдельного слоя очередей/воркеров для тяжёлых задач; все вычисления выполняются в рамках API-запросов или фонового планировщика.
  - Масштабирование по нагрузке потребует явных решений по горизонтальному масштабированию и/или выносу тяжёлых задач в отдельный контур.

- **Версионирование снапшотов**
  - Таблица `monitoring_snapshots` на текущий момент не содержит явного поля версии схемы снапшота.
  - Изменения структуры или смысла метрик потребуют аккуратных миграций и обратной совместимости на уровне сервисов и схем.

---

## Operating Rules

- Любая задача фиксируется в Change Log отдельной строкой (1–3 строки) в формате `YYYY-MM-DD — <что сделано>`.
- Любая новая сущность (endpoint, таблица, сервис) отражается в секциях **Implemented Modules** или **Active Stage**.
- Любая известная проблема или технический долг фиксируется в секции **Open Questions / Risks**.
- Любое изменение в коде или схемах должно фиксироваться коммитом в git и пушиться на настроенный удалённый репозиторий.
- Каждый завершённый мини-этап работы фиксируется коммитом в git, пушится на удалённый репозиторий и сопровождается записью в Change Log.

## 7. Change Log

| Date       | Change                                                                                     | Why                                                     |
|------------|--------------------------------------------------------------------------------------------|---------------------------------------------------------|
| 2025-12-29 | Добавлены и применены миграции для интеграционных и мониторинговых таблиц (0007, 0008).   | Устранить ошибки 500 из-за отсутствующих таблиц в БД.   |
| 2025-12-29 | Реализован Monitoring Scheduler (APScheduler) и интегрирован в жизненный цикл FastAPI.    | Обеспечить автоматическое построение мониторинг-снапшотов. |
| 2025-12-29 | Создан данный документ PROJECT_CANON.md.                                                   | Зафиксировать единый источник правды по проекту.        |
| 2025-12-29 | repo initialized, origin set to GitHub, initial baseline pushed (commit 2d120b8, branch main). | Зафиксировать привязку репозитория к GitHub и базовый коммит. |
| 2025-12-29 | Added PG advisory lock to prevent multi-instance scheduler duplication.                    | Сделать запуск планировщика single-instance при нескольких backend-инстансах. |
| 2025-12-29 | Verified multi-instance scheduler advisory lock with two backend services under Docker Compose. | Подтвердить, что при двух backend-инстансах только один получает lock и выполняет планировщик. |
| 2025-12-29 | Added Planning Core v1 skeleton (domain, service interface, 501 endpoints).                | Подготовить каркас ядра планирования без изменения текущей логики. |
