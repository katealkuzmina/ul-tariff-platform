-- Эталонный запрос витрины «Карточка маршрута и рыночный коридор ставок».
-- Грейн: месяц (price_dates.price_date) x город отправления x город назначения
--        x унифицированная группа кузова x весовая категория.
-- MoM/YoY — self-join по сдвинутому календарному месяцу (LAG не используется:
-- при пропуске месяца корректный результат — NULL, не «последний доступный»).
-- Параметр :as_of — дата снимка (плановые месяцы будущего исключены).
WITH fct AS (  -- факты месяца: grain = price_id x месяц x body_group, без размножения
  SELECT pd.price_date AS month_date,
         p.price_id, p.price_rub, p.distance, p.organization_id, p.price_type,
         p.loading_city_gcid, p.unloading_city_gcid, p.weight_category,
         g.body_group
  FROM core.prices_clean p
  JOIN public.price_dates pd ON pd.price_id = p.price_id
  JOIN core.price_body_groups g ON g.price_id = p.price_id
  WHERE p.is_fact AND NOT p.complex AND p.price_rub IS NOT NULL
    AND NOT p.outlier_mark                  -- рыночная витрина без статистических выбросов
    AND pd.price_date <= :as_of             -- плановые месяцы будущего исключены
),
cell AS (
  SELECT date_trunc('month', month_date)::date AS month_date,
         loading_city_gcid, unloading_city_gcid, body_group, weight_category,
         percentile_cont(0.25) WITHIN GROUP (ORDER BY price_rub)                          AS p25_trip,
         percentile_cont(0.50) WITHIN GROUP (ORDER BY price_rub)                          AS median_trip,
         percentile_cont(0.75) WITHIN GROUP (ORDER BY price_rub)                          AS p75_trip,
         avg(price_rub)                                                                   AS avg_trip,
         percentile_cont(0.25) WITHIN GROUP (ORDER BY price_rub / NULLIF(distance, 0))    AS p25_km,
         percentile_cont(0.50) WITHIN GROUP (ORDER BY price_rub / NULLIF(distance, 0))    AS median_km,
         percentile_cont(0.75) WITHIN GROUP (ORDER BY price_rub / NULLIF(distance, 0))    AS p75_km,
         count(DISTINCT price_id)                                                          AS trips_count,
         count(DISTINCT organization_id) FILTER (WHERE price_type IN (3, 9))               AS carriers_count,
         CASE WHEN count(*) >= 2 AND avg(price_rub) <> 0
              THEN stddev_samp(price_rub) / avg(price_rub) END                              AS cv_rate
  FROM fct
  GROUP BY 1, 2, 3, 4, 5
)
INSERT INTO mart.route_card (
    month_date, loading_gc_id, unloading_gc_id, loading_city, unloading_city,
    body_group, weight_category,
    p25_trip, median_trip, p75_trip, avg_trip,
    p25_km, median_km, p75_km,
    trips_count, carriers_count, cv_rate,
    mom_pct, yoy_pct, reliability_level, built_at
)
SELECT c.month_date,
       c.loading_city_gcid, c.unloading_city_gcid,
       cl.city_name, cu.city_name,
       c.body_group, c.weight_category,
       c.p25_trip, c.median_trip, c.p75_trip, c.avg_trip,
       c.p25_km, c.median_km, c.p75_km,
       c.trips_count, c.carriers_count, c.cv_rate,
       100.0 * (c.median_trip / NULLIF(p_prev.median_trip, 0) - 1) AS mom_pct,
       100.0 * (c.median_trip / NULLIF(p_yoy.median_trip, 0) - 1)  AS yoy_pct,
       CASE
           WHEN c.trips_count >= 30 AND c.carriers_count >= 5
                AND (:as_of - c.month_date) <= 30 THEN 'HIGH'
           WHEN c.trips_count >= 10 THEN 'MEDIUM'
           ELSE 'LOW_DATA'
       END AS reliability_level,
       now()
FROM cell c
JOIN core.dim_cities cl ON cl.gc_id = c.loading_city_gcid
JOIN core.dim_cities cu ON cu.gc_id = c.unloading_city_gcid
LEFT JOIN cell p_prev
       ON p_prev.month_date = c.month_date - interval '1 month'
      AND p_prev.loading_city_gcid = c.loading_city_gcid
      AND p_prev.unloading_city_gcid = c.unloading_city_gcid
      AND p_prev.body_group = c.body_group
      AND p_prev.weight_category = c.weight_category
LEFT JOIN cell p_yoy
       ON p_yoy.month_date = c.month_date - interval '1 year'
      AND p_yoy.loading_city_gcid = c.loading_city_gcid
      AND p_yoy.unloading_city_gcid = c.unloading_city_gcid
      AND p_yoy.body_group = c.body_group
      AND p_yoy.weight_category = c.weight_category;
