-- 03_mart.sql — аналитический слой витрин для BI и ML-контура.
CREATE SCHEMA IF NOT EXISTS mart;

-- Карточка маршрута и рыночный коридор ставок.
CREATE TABLE IF NOT EXISTS mart.route_card (
    month_date       date        NOT NULL,
    loading_gc_id    integer     NOT NULL,
    unloading_gc_id  integer     NOT NULL,
    loading_city     text        NOT NULL,
    unloading_city   text        NOT NULL,
    body_group       varchar(32) NOT NULL,
    weight_category  varchar(4)  NOT NULL,
    p25_trip         numeric,
    median_trip      numeric,
    p75_trip         numeric,
    avg_trip         numeric,
    p25_km           numeric,
    median_km        numeric,
    p75_km           numeric,
    trips_count      integer     NOT NULL,
    carriers_count   integer     NOT NULL,
    cv_rate          numeric,
    mom_pct          numeric,
    yoy_pct          numeric,
    reliability_level text       NOT NULL,
    built_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (month_date, loading_gc_id, unloading_gc_id, body_group, weight_category)
);

-- Пакетный скоринг: факт vs прогноз по каждой оценённой сделке.
CREATE TABLE IF NOT EXISTS mart.ml_price_predictions (
    price_id             bigint      NOT NULL,
    loading_date         date        NOT NULL,
    loading_city_gcid    integer     NOT NULL,
    unloading_city_gcid  integer     NOT NULL,
    body_group           varchar(32) NOT NULL,
    actual_price_rub     numeric,
    predicted_price_rub  numeric     NOT NULL,
    abs_error_rub        numeric,
    ape_pct              numeric,
    model_name           text        NOT NULL,
    scored_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ml_price_predictions_model_idx ON mart.ml_price_predictions (model_name);
CREATE INDEX IF NOT EXISTS ml_price_predictions_date_idx ON mart.ml_price_predictions (loading_date);

-- Метрики качества моделей на отложенной тестовой выборке.
CREATE TABLE IF NOT EXISTS mart.model_metrics (
    model_name  text        NOT NULL,
    trained_at  timestamptz NOT NULL DEFAULT now(),
    train_rows  integer     NOT NULL,
    test_rows   integer     NOT NULL,
    r2          numeric,
    mape_pct    numeric,
    rmse_rub    numeric,
    mae_rub     numeric,
    params      jsonb       NOT NULL DEFAULT '{}'::jsonb
);
