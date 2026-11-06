-- 01_raw.sql — базовый слой: зеркало источника за обрабатываемое окно дат.
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.prices (LIKE public.prices INCLUDING ALL);
CREATE TABLE IF NOT EXISTS raw.price_dates (LIKE public.price_dates INCLUDING ALL);

CREATE INDEX IF NOT EXISTS raw_prices_loading_date_idx ON raw.prices (loading_date);
CREATE INDEX IF NOT EXISTS raw_price_dates_price_id_idx ON raw.price_dates (price_id);
