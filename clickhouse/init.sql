CREATE DATABASE IF NOT EXISTS mart;

-- Реплика витрины «Карточка маршрута» для быстрого BI-сканирования.
CREATE TABLE IF NOT EXISTS mart.route_card
(
    month_date        Date,
    loading_gc_id     Int32,
    unloading_gc_id   Int32,
    loading_city      String,
    unloading_city    String,
    body_group        LowCardinality(String),
    weight_category   LowCardinality(String),
    p25_trip          Nullable(Float64),
    median_trip       Nullable(Float64),
    p75_trip          Nullable(Float64),
    avg_trip          Nullable(Float64),
    p25_km            Nullable(Float64),
    median_km         Nullable(Float64),
    p75_km            Nullable(Float64),
    trips_count       UInt32,
    carriers_count    UInt32,
    cv_rate           Nullable(Float64),
    mom_pct           Nullable(Float64),
    yoy_pct           Nullable(Float64),
    reliability_level LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (month_date, loading_gc_id, unloading_gc_id, body_group, weight_category);
