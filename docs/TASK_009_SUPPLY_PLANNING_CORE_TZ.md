# TASK #9 — Supply Planning Core: per-article settings + production order proposal

## 1) Цель задачи
Сделать ядро расчета **предложения заказа в Китай** для одного артикула (с архитектурой для масштабирования), чтобы:
- не уходить в out-of-stock,
- не перетаривать склад,
- учитывать реальные ограничения фабрики,
- выдавать закупщику объяснимое решение и альтернативы.

Ключевой результат задачи: новый API-метод, который возвращает **production order proposal** (рекомендацию), а не автоматически создает заказ.

---

## 2) Контекст и инварианты

### 2.1 Что уже есть в проекте
- FastAPI backend, SQLAlchemy, PostgreSQL.
- Сущности по артикулам/цветам/размерам/рецептам наборов/остаткам.
- Настройки планирования:
  - `global_planning_settings`
  - `article_planning_settings`
  - `color_planning_settings`
  - `elastic_planning_settings`
  - `planning_settings`.

### 2.2 Бизнес-инварианты (обязательные)
1. Китай получает заказ в разрезе **article + color + size + qty**, а не по наборам.
2. Минималка ткани применяется по цвету/Pantone (базово ~7000, но настраивается).
3. Минималка резинки применяется по типу резинки/артикулу (базово ~3000, но настраивается).
4. Один и тот же сырьевой SKU может потребляться разными наборами (4/5/6) — конкуренцию нужно учитывать.
5. Дефицит для планирования заказа — по модели **B**:
   - целевой объем по наборам считается суммарно,
   - распределение по размерам делается через веса/пропорции,
   - не умножать target_count на каждый размер.
6. Любая рекомендация должна содержать human-readable объяснение.
7. Нельзя ломать существующие API контракты.

---

## 3) Scope TASK #9 (что делаем сейчас)

### 3.1 Включено
- Новый расчетный endpoint для **proposal** (без интеграции с WB API, входные данные подаются в запросе).
- Учет текущих остатков:
  - готовые наборы WB,
  - готовые наборы локальный склад,
  - сырьевые штучные SKU локальный склад,
  - pipeline-поставки (в производстве/в пути) из входных данных.
- Учет полного цикла поставки:
  - производство,
  - Китай -> НСК,
  - упаковка,
  - НСК -> WB.
- Учет минималок ткани/резинки + ручные override.
- Пер-артикульные флаги: включать/исключать из расчета, приоритет.
- Генерация альтернатив в спорных точках (ждать / заказать с запасом).
- Человеческое объяснение логики.

### 3.2 Не включено в TASK #9
- Прямая онлайн-интеграция WB API и МойСклад API.
- Полноценный ML forecasting pipeline.
- Автосоздание финального PO в БД с workflow согласования.

---

## 4) Значения по умолчанию (конфигурируемые)
- `target_coverage_days`: 60 (пользователь может менять, обычно 60-90).
- `service_level_percent`: 90.
- `alert_threshold_days`: 90.
- `lead_time_days_total`: 70 (30 + 30 + 3 + 7), с возможностью override компонентов.
- `fabric_min_batch_qty_default`: 7000.
- `elastic_min_batch_qty_default`: 3000.

Все значения должны поддерживать override в запросе.

---

## 5) Требуемые изменения в коде

### 5.1 Новые схемы
Создать файл:
- `app/schemas/planning_production_order.py`

Минимальные модели:
1. `ProductionOrderProposalRequest`
2. `BundleDemandInput`
3. `BundleStockInput`
4. `InFlightSupplyInput`
5. `PlanningOverridesInput`
6. `ProductionOrderProposalResponse`
7. `ProductionOrderRecommendationLine`
8. `ProductionOrderAlternative`
9. `ProductionOrderExplanationBlock`

### 5.2 Новый сервис
Создать файл:
- `app/services/planning_production_order.py`

Главная функция:
- `build_production_order_proposal(db: Session, request: ProductionOrderProposalRequest) -> ProductionOrderProposalResponse`

### 5.3 Новый endpoint
Обновить:
- `app/api/v1/endpoints/planning_core.py`

Добавить:
- `POST /api/v1/planning/core/production-order/proposal`

### 5.4 Тесты
Создать:
- `tests/test_planning_core_production_order_api.py`

Сценарии минимум:
1. Happy path: корректный proposal для одного артикула.
2. `include_in_planning=false` -> статус `skipped` с пояснением.
3. Срабатывание минималки ткани.
4. Срабатывание минималки резинки.
5. Альтернативы в спорной ситуации (wait vs order_with_buffer).
6. Валидация входных параметров (400/422).

---

## 6) Контракт нового API

## 6.1 Endpoint
`POST /api/v1/planning/core/production-order/proposal`

## 6.2 Пример request (MVP)
```json
{
  "article_id": 9,
  "planning_horizon_days": 90,
  "bundle_daily_sales": [
    {"bundle_type_id": 1, "daily_sales": 10.0},
    {"bundle_type_id": 2, "daily_sales": 4.0},
    {"bundle_type_id": 3, "daily_sales": 3.0}
  ],
  "bundle_stock": [
    {"bundle_type_id": 1, "wb_qty": 100, "local_qty": 500},
    {"bundle_type_id": 2, "wb_qty": 60, "local_qty": 120},
    {"bundle_type_id": 3, "wb_qty": 40, "local_qty": 80}
  ],
  "in_flight_supply": [
    {
      "article_id": 9,
      "color_id": 11,
      "size_id": 4,
      "qty": 300,
      "eta_days": 45,
      "stage": "china_to_nsk"
    }
  ],
  "size_weights": {
    "1": 0.08,
    "2": 0.12,
    "3": 0.16,
    "4": 0.18,
    "5": 0.18,
    "6": 0.14,
    "7": 0.09,
    "8": 0.05
  },
  "overrides": {
    "target_coverage_days": 60,
    "service_level_percent": 90,
    "alert_threshold_days": 90,
    "lead_time_days": {
      "production": 30,
      "china_to_nsk": 30,
      "packaging": 3,
      "nsk_to_wb": 7
    },
    "fabric_min_batch_qty_default": 7000,
    "elastic_min_batch_qty_default": 3000,
    "allow_order_with_buffer": true
  }
}
```

## 6.3 Пример response (MVP)
```json
{
  "status": "ok",
  "article_id": 9,
  "generated_at": "2026-02-24T14:00:00Z",
  "risk_level": "warning",
  "days_of_cover_estimate": 84.2,
  "lead_time_days_total": 70,
  "recommendation": {
    "action": "order_with_buffer",
    "priority": 2,
    "target_arrival_date": "2026-05-10",
    "total_units": 14600,
    "lines": [
      {
        "article_id": 9,
        "color_id": 11,
        "size_id": 4,
        "recommended_qty": 1300,
        "source_reason": "deficit_plus_min_batch_alignment"
      }
    ]
  },
  "constraints_applied": {
    "fabric_min_batches": [
      {"pantone_code": "BLACK-01", "required": 6200, "applied_min": 7000}
    ],
    "elastic_min_batches": [
      {"article_id": 9, "elastic_type_id": 2, "required": 2200, "applied_min": 3000}
    ]
  },
  "alternatives": [
    {
      "action": "wait",
      "pros": ["меньше заморозка средств"],
      "cons": ["высокий риск OOS до следующего цикла заказа"]
    }
  ],
  "explanation": {
    "summary": "Запас по ключевому набору опускается ниже порога 90 дней при lead time 70 дней.",
    "steps": [
      "Спрогнозирован спрос по 4/5/6-pack на горизонт 90 дней.",
      "Учтены текущие готовые наборы WB/локальный склад и сырьевые остатки.",
      "Рассчитан дефицит по модели B и распределен по размерам через size_weights.",
      "Применены минималки ткани и резинки; недобор добран с буфером."
    ]
  }
}
```

---

## 7) Алгоритм расчета (MVP)

1. Загрузить артикул и настройки (global + article + planning_settings + color/elastic settings).
2. Если артикул исключен из планирования -> вернуть `status=skipped`.
3. Собрать рецепты наборов (`bundle_recipe`) для всех `bundle_type_id`, пришедших в запросе.
4. Посчитать прогноз потребления наборов на горизонт:
   - `expected_bundle_sales = daily_sales * planning_horizon_days`
5. Сложить доступный запас наборов:
   - `ready_stock = wb_qty + local_qty`.
6. Посчитать, сколько наборов можно дособрать из сырья (`stock_balance` + `sku_unit` + `bundle_recipe`) с учетом конкуренции наборов за сырье.
7. Вычислить целевой объем пополнения до `target_coverage_days`.
8. Конвертировать потребность наборов в потребность по `article+color+size`:
   - модель B: target для набора суммарный,
   - распределение по размерам через `size_weights`.
9. Учесть `in_flight_supply`, если ETA <= целевой точки дефицита.
10. Агрегировать дефицит:
   - per color+size,
   - per Pantone/group.
11. Применить минималки:
   - ткань: min по Pantone,
   - резинка: min по article+elastic_type.
12. Если после минималок есть избыток, распределить излишек пропорционально size_weights.
13. Оценить риск OOS (days_of_cover vs lead_time vs alert_threshold).
14. Сформировать варианты:
   - `wait`,
   - `order_with_buffer`,
   - `order_minimum_only`.
15. Выбрать recommended action (эвристика MVP):
   - если OOS до следующего цикла вероятен -> `order_with_buffer`,
   - иначе `wait` или `order_minimum_only`.
16. Сгенерировать explanation.

---

## 8) Правила принятия решения (MVP)

1. **По умолчанию система рекомендует, не приказывает**.
2. Во всех спорных кейсах возвращать минимум 2 альтернативы.
3. Если риск OOS до прихода следующей партии высокий, recommendation смещается в сторону `order_with_buffer`.
4. Если риск OOS низкий и заморозка денег высокая, recommendation смещается в `wait`.
5. Для каждого решения обязательно текстовое обоснование.

---

## 9) Требования к объяснению (обязательно)
`explanation` должен отвечать минимум на 5 вопросов:
1. Почему именно сейчас нужен/не нужен заказ?
2. Какие данные повлияли на решение сильнее всего?
3. Какие минималки сработали?
4. Почему появился буфер (если появился)?
5. Что будет, если выбрать альтернативу?

---

## 10) Нефункциональные требования
- Детерминированный расчет для одинакового входа.
- Не использовать внешние API в рамках TASK #9.
- Код разделить на маленькие чистые функции (forecast, minima, allocation, explanation).
- Сохранить обратную совместимость текущих endpoint-ов.
- Покрыть тестами ключевую логику.

---

## 11) Acceptance criteria
1. Новый endpoint доступен и возвращает валидный JSON proposal.
2. Учитываются настройки статьи и override из запроса.
3. Дефицит считается по модели B (суммарный target, не per-size умножение).
4. Минималки ткани и резинки применяются корректно.
5. В response есть альтернативы и human-readable explanation.
6. Существующие endpoint-ы продолжают работать без изменения контракта.
7. Добавлены тесты на happy-path и граничные сценарии.

---

## 12) Этап после TASK #9
- Подключить реальный WB forecasting ingestion.
- Добавить сохранение драфтов ProductionOrder и workflow подтверждения.
- Добавить экономическую модель OOS cost vs inventory holding cost.
- Добавить исторический профайл фабрики (скорость/задержки/CNY) в scoring рекомендаций.
