-- 02_core.sql — очищенный и согласованный слой фактов + справочники.
CREATE SCHEMA IF NOT EXISTS core;

-- Карантин Data Quality: отбракованные строки не теряются, хранятся с кодом причины.
CREATE TABLE IF NOT EXISTS core.dq_quarantine_prices (
    price_id        bigint      NOT NULL,
    loading_date    date        NOT NULL,
    reason_code     text        NOT NULL,
    payload         jsonb       NOT NULL,
    quarantined_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (price_id, reason_code)
);
CREATE INDEX IF NOT EXISTS dq_quarantine_loading_date_idx ON core.dq_quarantine_prices (loading_date);

-- Очищенные факты сделок: одна строка на сделку, ставка приведена к RUB без НДС.
CREATE TABLE IF NOT EXISTS core.prices_clean (
    price_id            bigint PRIMARY KEY,
    loading_date        date             NOT NULL,
    loading_city_gcid   integer          NOT NULL,
    unloading_city_gcid integer          NOT NULL,
    distance            double precision NOT NULL,
    total_weight        double precision NOT NULL,
    total_volume        double precision NOT NULL,
    body_type           integer,
    price               double precision NOT NULL,
    currency_code       varchar(3)       NOT NULL DEFAULT '643',
    price_rub           numeric(14, 2),
    complex             boolean          NOT NULL DEFAULT false,
    price_type          smallint         NOT NULL DEFAULT 2,
    is_fact             boolean          NOT NULL DEFAULT true,
    organization_id     integer,
    outlier_mark        boolean          NOT NULL DEFAULT false,
    weight_category     varchar(4),
    volume_category     varchar(4),
    loaded_at           timestamptz      NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS prices_clean_loading_date_idx ON core.prices_clean (loading_date);
CREATE INDEX IF NOT EXISTS prices_clean_route_idx ON core.prices_clean (loading_city_gcid, unloading_city_gcid, weight_category, volume_category);

-- Унифицированные бизнес-группы кузова: одна сделка — максимум одна строка на группу.
CREATE TABLE IF NOT EXISTS core.price_body_groups (
    price_id    bigint      NOT NULL,
    body_group  varchar(32) NOT NULL,
    PRIMARY KEY (price_id, body_group)
);

-- Справочник городов с устранёнными дублями gc_id (запись с минимальным cities.id).
CREATE TABLE IF NOT EXISTS core.dim_cities (
    gc_id       integer PRIMARY KEY,
    city_id     bigint,
    city_name   text,
    region      text,
    latitude    double precision,
    longitude   double precision
);
