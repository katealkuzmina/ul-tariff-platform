# Smart Logistics Data & ML Platform — тарифы грузоперевозок

Тестовое задание Middle Data Engineer («Умная Логистика»): сквозной прототип
платформы аналитики транспортных ставок — от сырых сделок операционной БД до
рыночного коридора P25/P50/P75 в витрине BI и ML-прогноза тарифа с batch-скорингом.

## Быстрый старт

Требуется только Docker. Одна команда поднимает PostgreSQL 17 с детерминированными
тестовыми данными (300 000 сделок) и выполняет весь пайплайн
(миграции → ETL → витрины → обучение → скоринг):

```bash
docker-compose up --build
```

Сервис `app` — one-shot: дождитесь строк `=== Model metrics (test window) ===` в логах
(`docker compose logs -f app`), после чего контейнер завершится с кодом 0.
Подключение к БД с хоста: `psql -h localhost -p 5433 -U postgres -d deals_bigdata`
(порт 5433, т.к. 5432 часто занят локальным PostgreSQL; внутри сети compose — `db:5432`).

Переменные окружения копируются из `.env.example` в `.env` (значения по умолчанию
работают без правок).

## Что проверять после прогона

```sql
-- 1. Рыночный коридор: топ-10 ячеек по медиане за последний месяц
SELECT month_date, loading_city, unloading_city, body_group, weight_category,
       p25_trip, median_trip, p75_trip, median_km,
       trips_count, carriers_count, cv_rate, mom_pct, reliability_level
FROM mart.route_card
WHERE month_date = (SELECT max(month_date) FROM mart.route_card)
ORDER BY median_trip DESC
LIMIT 10;

-- 2. Карантин Data Quality: статистика отбраковки по причинам
SELECT reason_code, count(*) FROM core.dq_quarantine_prices GROUP BY 1 ORDER BY 2 DESC;

-- 3. Факт vs Прогноз: точность модели на тестовом окне
SELECT count(*) AS scored,
       round(avg(ape_pct), 2) AS mape_pct,
       round(avg(abs_error_rub), 0) AS mae_rub
FROM mart.ml_price_predictions
WHERE model_name = 'catboost_v1' AND loading_date <= DATE '2026-10-26';

-- 4. Плановые заявки будущего: прогноз без факта
SELECT price_id, loading_date, loading_city_gcid, unloading_city_gcid,
       body_group, predicted_price_rub
FROM mart.ml_price_predictions
WHERE model_name = 'catboost_v1' AND loading_date > DATE '2026-10-26'
LIMIT 10;

-- 5. Метрики обеих моделей
SELECT model_name, train_rows, test_rows, r2, mape_pct, rmse_rub, mae_rub
FROM mart.model_metrics ORDER BY model_name;
```

## Архитектура

```
public (операционная БД deals_bigdata, источник)
  │  etl/extract.py  — выборка окна loading_date в raw (COPY, идемпотентно)
  ▼
raw      — зеркало источника за обработанное окно (raw.prices, raw.price_dates)
  │  etl/load.py    — валидация DQ, конвертация валют, категории, карантин
  ▼
core     — core.prices_clean (1 строка = 1 сделка, price_rub numeric(14,2)),
           core.dq_quarantine_prices (отбракованные строки + код причины + payload),
           core.dim_cities (gc_id дедуплицирован min(id)),
           core.price_body_groups (std_id-группы кузова, DISTINCT price_id × группа)
  │  etl/mart.py    — полный рефреш в транзакции (sql/mart/mart_route_card.sql)
  ▼
mart     — mart.route_card (рыночный коридор + Data Trust),
           mart.ml_price_predictions (факт vs прогноз),
           mart.model_metrics (R², MAPE, RMSE, MAE)

ml/      — ml/features.py (признаки + защита от утечек), ml/dataset.py (time-split),
           ml/train.py (CatBoost + Ridge-бейзлайн), ml/predict.py (batch-скоринг)
```

**Идемпотентность.** Каждый шаг переживает повторный запуск за тот же период:
загрузка окна и карантин — `DELETE WHERE loading_date BETWEEN … + INSERT` в одной
транзакции; витрина — `TRUNCATE + INSERT`; метрики и прогнозы — `DELETE по model_name +
INSERT`. Повторный `docker-compose up` не дублирует строки.

**Бэкфилл за произвольное окно:**

```bash
make etl START=2026-10-01 END=2026-10-26   # затем make mart && make ml
# или напрямую:
docker compose run --rm app etl --start 2026-10-01 --end 2026-10-26
```

Отдельные ступени: `migrate` (только миграции), `mart` (пересчёт витрины),
`ml` (обучение + скоринг). Полный список: `make help`-цели в `Makefile`.

## Правила Data Quality (Вопрос 1)

| Проверка | Условие отбраковки | Код причины |
|---|---|---|
| Нулевая/отрицательная ставка | `price <= 0` | `INVALID_PRICE` |
| Source-validation диапазон RUB | `currency_code='643' AND price <= 1000` | `INVALID_PRICE_RANGE` |
| Дистанция | `distance <= 0` | `INVALID_DISTANCE` |
| Вес | `total_weight < 0` | `INVALID_WEIGHT` |
| Объём | `total_volume < 0` | `INVALID_VOLUME` |
| Город вне справочника | gc_id отсутствует в `cities` | `CITY_NOT_FOUND` |
| Валюта без точного курса | `currency_code <> '643'` и нет курса ЦБ на `nearest_rate_date` | `FX_RATE_MISSING` |

- Конвертация в RUB: `price_rub = price × курс ЦБ(num_code, nearest_rate_date)`;
  для RUB курс = 1. Fallback по `loading_date` не используется (по требованию ТЗ).
- Категории веса пересчитываются всегда, по весу с округлением до 0.1 т
  (HALF_UP, как `round(numeric, 1)` в PostgreSQL): `G20T` ≥30, `FTL` [10;30),
  `10T` [5;10), `5T` [2.5;5), `L5T` [0.5;2.5), иначе `OTH`.
  Объём: `FTL` при 0 < V ≤ 120 м³, иначе `OTH`.
- `outlier_mark = true` исключается из рыночной витрины и обучающей выборки.
  **Ограничение исходных данных:** сделки за последний день снимка (2026-10-26)
  ещё не прошли ночной джоб разметки аномалий и имеют `outlier_mark = false`
  по умолчанию — они попадают в витрину/обучение как немаркированные.
- Отбракованные строки не теряются: `core.dq_quarantine_prices` хранит код причины
  и исходную строку (`payload jsonb`).

## Витрина «Карточка маршрута» (Вопрос 2)

- **Грейн:** месяц (`price_dates.price_date`, долгосрочная заявка учитывается в каждом
  месяце периода) × город отправления × город назначения × группа кузова × весовая
  категория. `volume_category` — атрибут, в грейн не входит.
- **Фильтры:** фактические завершённые прямые перевозки (`is_fact`, `complex = false`),
  валидные `price_rub`/`distance`, без `outlier_mark`, `price_date <= as_of (2026-10-26)`.
- **Дедупликация городов:** `gc_id` не уникален в `cities` → `DISTINCT ON (gc_id) …
  ORDER BY gc_id, id` (запись с минимальным `id`).
- **Группы кузова** по `std_id`: Тент=56 (56–61), Рефрижератор=4 (4, 46–48),
  Изотерм=2, Борт=15 (1, 15), Прочие (остальные), Не указан (NULL / нет связи,
  fallback на `prices.body_type`). Одна цена — одна строка внутри группы (`DISTINCT`).
- Витрина читает календарь из операционной `public.price_dates` (как эталонный запрос
  спецификации); зеркало `raw.price_dates` сохраняет снимок извлечённого окна
  для аудита слоя raw.
- **Метрики:** P25/P50/P75 и AVG в руб./рейс и руб./км (`percentile_cont`);
  `trips_count` = число уникальных сделок; `carriers_count` = число уникальных
  перевозчиков (`price_type IN (3, 9)`); `cv_rate` = `stddev_samp/avg` (NULL при n<2
  или avg=0); `mom_pct`/`yoy_pct` = изменение P50 к **фактическому** предыдущему месяцу
  / тому же месяцу год назад (self-join по сдвинутому календарному месяцу — не `LAG()`,
  при отсутствии ячейки результат NULL, «последний доступный» не подставляется);
  `reliability_level`: HIGH (trips ≥ 30, carriers ≥ 5, свежесть месяца ≤ 30 дней от
  `as_of`), MEDIUM (trips ≥ 10), иначе LOW_DATA.

## ML-контур (Вопрос 3)

- **Таргет:** `price_rub` (фактическая ставка перевозчика за рейс, RUB без НДС).
- **Time-Based Split** от фиксированной даты снимка `as_of = 2026-10-26`
  (системная дата не используется):
  train = `[2026-07-26, 2026-10-05)`, test = `[2026-10-05, 2026-10-26]`;
  граница `2026-10-05` входит только в test; `shuffle` запрещён.
  Обучающая выборка дополнительно без `outlier_mark = true`.
- **Признаки:** регион/город отправления и назначения (раздельно, из
  `cities.full_name_local` + координаты), расстояние, тоннаж, объём, группа кузова,
  весовая/объёмная категории, год и циклические гармоники месяца (T=12), дня недели
  (T=7) и дня года (T=365.25).
- **Защита от утечек:** исключены таргет-производные и постфактум-агрегаты —
  `price`, `price_rub`, `price_with_vat`, удельные тарифы текущего рейса,
  `price_group_stats` (`avg_price`, `min_km_price`, `max_km_price`, `price_group_id`),
  `outlier_mark` (не используется как признак), служебные идентификаторы
  (`organization_id`, `subscriber_id`, `nearest_rate_date`). Препроцессинг Ridge
  (imputer/scaler/one-hot) обучается строго на train (`build_xy` падает, если
  запрещённая колонка проникла в X).
- **Модели:** `CatBoostRegressor` (RMSE, `random_seed=42`, нативные категориальные
  признаки) и линейный бейзлайн `Ridge` (SimpleImputer + StandardScaler + OneHot).
- **Воспроизводимость:** детерминированный генератор (`setseed(0.20261026)`),
  фиксированные границы сплита, фиксированный seed обучения.

### Метрики на тестовой выборке

| Модель | R² | MAPE, % | RMSE, руб. | MAE, руб. | train / test строк |
|---|---|---|---|---|---|
| CatBoost | 0.789 | 19.48 | 94 781 | 35 597 | 24 226 / 13 078 |
| Ridge | 0.732 | 52.53 | 107 007 | 54 510 | 24 226 / 13 078 |

*(получены на детерминированном датасете 300 000 сделок; воспроизводятся
`docker-compose up` и хранятся в `mart.model_metrics`. CatBoost превосходит
линейный бейзлайн по всем метрикам; MAPE/R² отличаются от ориентиров R&D-отчёта,
т.к. рассчитаны на синтетическом датасете задания)*

- **Batch-скоринг** (`mart.ml_price_predictions`): факты тестового окна с
  `actual_price_rub` и ошибками + плановые заявки будущего (`loading_date >
  2026-10-26`) с `actual_price_rub IS NULL`, `abs_error_rub IS NULL`,
  `ape_pct IS NULL` — даже если цена в исходной строке заполнена.
  Для сделки с несколькими группами кузова скоринг ведётся на канонической
  (минимальной по алфавиту) группе — одна строка на `price_id`.

## Бонус-задачи (★): Airflow, Superset, ClickHouse

Бонусные сервисы не участвуют в базовом сценарии и поднимаются отдельным профилем —
`docker-compose up` остаётся минимальным и детерминированным:

```bash
docker compose --profile bonus up -d     # airflow-init/scheduler/webserver, clickhouse, superset
```

### Apache Airflow (`dags/`)

DAG `tariff_pipeline` (LocalExecutor, мета-БД `airflow` в той же PostgreSQL):
таски `migrate → etl → mart → train → score`, вызывающие те же функции, что и
сервис `app` (идемпотентность сохраняется). Расписание отключено (`schedule=None`) —
запуск вручную из UI (http://localhost:8080, admin/admin) или CLI:

```bash
docker compose exec airflow-webserver airflow dags trigger tariff_pipeline
# бэкфилл окна:
docker compose exec airflow-webserver airflow dags trigger tariff_pipeline \
  --conf '{"start_date": "2026-10-01", "end_date": "2026-10-26"}'
```

### Apache Superset

http://localhost:8088 (admin/admin после `docker compose --profile bonus up -d superset`).
init-скрипт (`docker/superset/init.sh`) создаёт admin и подключение `deals_bigdata`.
Рекомендуемые дашборды по двум пользовательским сценариям:

1. **Сводный анализ маршрутной сети** — таблица `mart.route_card`: фильтры
   `month_date`, `body_group`, `weight_category`; колонки коридоров
   `p25/median/p75_trip`, `median_km`, `mom_pct`, `reliability_level`.
2. **Карточка маршрута** — помесячная история по паре городов + график
   «Факт vs Прогноз» из `mart.ml_price_predictions` (`actual_price_rub` vs
   `predicted_price_rub`, разрез `loading_date`).

### ClickHouse-реплика витрины

Сервис `clickhouse` (http://localhost:8123, БД `mart`, таблица `route_card` на
`MergeTree ORDER BY (month_date, loading_gc_id, unloading_gc_id, body_group,
weight_category)`). Репликация идемпотентна (TRUNCATE + батчевый insert):

```bash
REPLICATE_TO_CH=1 docker compose run --rm app mart
```

## Тесты

```bash
make test        # pytest внутри контейнера app (тот же образ, что и пайплайн)
# или локально: uv sync && uv run pytest
```

51 тест: границы категорий и правила DQ, идемпотентность ETL/витрины/скоринга,
синхронизация raw с источником, грейн витрины и инварианты коридора, отсутствие
leakage-колонок, границы time-split, детерминизм CatBoost, скейлер Ridge только
на train, покрытие скорингом тестового окна и будущего.

## Структура репозитория

```
├── docker-compose.yml          # db (postgres:17 + инициализация источника) + app (one-shot)
├── Dockerfile.app              # python 3.12 + uv, postgresql-client
├── .env.example                # все параметры через env
├── Makefile                    # up / app / etl / mart / ml / test / psql
├── sql/
│   ├── source/                 # эталонная схема и генератор источника (из ТЗ)
│   ├── dwh/                    # DDL слоёв raw/core/mart (+ мигратор etl/migrate.py)
│   └── mart/mart_route_card.sql# эталонный запрос витрины коридора
├── etl/                        # extract / transform / load / pipeline / mart / runner
├── ml/                         # features / dataset / train / evaluate / predict
├── tests/                      # pytest (51 тест)
└── docker/                     # entrypoint-скрипты initdb и app
```

## Стек и обоснование

- **PostgreSQL 17** — единое хранилище слоёв `raw → core → mart` (прототип;
  в проде аналитический слой логично вынести в ClickHouse — см. бонус-ветку).
  Витрина считается чистым SQL (`percentile_cont`, `FILTER`, self-join) — дёшево
  поддерживать и reviewed-аналитиками.
- **COPY (psycopg3)** для загрузки — быстрее построчных INSERT на порядки;
  всё равно оконная идемпотентность через `DELETE+INSERT` в транзакции.
- **pandas** для DQ-трансформаций — читаемые векторизованные правила с
  юнит-тестами на границах.
- **CatBoost** — рекомендация R&D-отчёта для табличных данных с категориями;
  Ridge — честный линейный бейзлайн с train-only препроцессингом.
- Конфигурация только через переменные окружения; секретов в репозитории нет
  (`.env` в `.gitignore`, поставляется `.env.example`).
