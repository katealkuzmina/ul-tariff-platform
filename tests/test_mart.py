from datetime import date, timedelta

from sqlalchemy import text


def _ensure_data(conn):
    from etl.pipeline import run_etl

    run_etl(conn, date(2026, 7, 1), date(2026, 10, 26))


def test_route_card_grain_and_invariants(conn):
    from etl.config import get_settings
    from etl.mart import build_route_card

    _ensure_data(conn)
    rep = build_route_card(conn, get_settings().as_of)
    assert rep.rows > 0
    dup = conn.execute(
        text(
            """SELECT count(*) FROM (SELECT month_date, loading_gc_id, unloading_gc_id, body_group, weight_category
               FROM mart.route_card GROUP BY 1,2,3,4,5 HAVING count(*) > 1) t"""
        )
    ).scalar()
    assert dup == 0
    bad = conn.execute(
        text(
            """SELECT count(*) FROM mart.route_card
               WHERE NOT (p25_trip <= median_trip AND median_trip <= p75_trip)
                  OR NOT (p25_km <= median_km AND median_km <= p75_km)
                  OR trips_count <= 0 OR carriers_count > trips_count
                  OR month_date > DATE '2026-10-26'"""
        )
    ).scalar()
    assert bad == 0
    null_cv = conn.execute(
        text("SELECT count(*) FROM mart.route_card WHERE trips_count < 2 AND cv_rate IS NOT NULL")
    ).scalar()
    assert null_cv == 0
    levels = set(conn.execute(text("SELECT DISTINCT reliability_level FROM mart.route_card")).scalars())
    assert levels <= {"HIGH", "MEDIUM", "LOW_DATA"} and "LOW_DATA" in levels


def test_route_card_rerun_idempotent(conn):
    from etl.mart import build_route_card

    _ensure_data(conn)
    n1 = build_route_card(conn, date(2026, 10, 26)).rows
    n2 = build_route_card(conn, date(2026, 10, 26)).rows
    assert n1 == n2 > 0


def test_route_card_consistent_with_facts(conn):
    from etl.mart import build_route_card

    _ensure_data(conn)
    build_route_card(conn, date(2026, 10, 26))
    cell = conn.execute(
        text(
            "SELECT month_date, loading_gc_id, unloading_gc_id, body_group, weight_category, trips_count "
            "FROM mart.route_card ORDER BY trips_count DESC LIMIT 1"
        )
    ).one()
    month_date, lgc, ugc, bg, wc, trips = cell
    manual = conn.execute(
        text(
            """
            SELECT count(DISTINCT p.price_id)
            FROM core.prices_clean p
            JOIN public.price_dates pd ON pd.price_id = p.price_id
            JOIN core.price_body_groups g ON g.price_id = p.price_id
            WHERE p.is_fact AND NOT p.complex AND p.price_rub IS NOT NULL
              AND NOT p.outlier_mark
              AND pd.price_date <= DATE '2026-10-26'
              AND date_trunc('month', pd.price_date)::date = :m
              AND p.loading_city_gcid = :lgc AND p.unloading_city_gcid = :ugc
              AND g.body_group = :bg AND p.weight_category = :wc
            """
        ),
        {"m": month_date, "lgc": lgc, "ugc": ugc, "bg": bg, "wc": wc},
    ).scalar()
    assert manual == trips


def test_route_card_mom_yoy_against_independent_recompute(conn):
    """Review Focus #5: mom_pct/yoy_pct — self-join по сдвинутому календарному месяцу.
    1) Для плотной ячейки пересчитываем медиану прошлого месяца независимым
       агрегатом (без обращения к mart) и сверяем mom_pct.
    2) На синтетической паре городов с единственным месяцем: mom/yoy = NULL
       (отсутствие соседней ячейки не должно подставлять «последний доступный» месяц)."""
    from etl.config import get_settings
    from etl.mart import build_route_card
    from etl.pipeline import run_etl

    as_of = get_settings().as_of
    _ensure_data(conn)
    build_route_card(conn, as_of)

    cell = conn.execute(
        text(
            """SELECT month_date, loading_gc_id, unloading_gc_id, body_group,
                      weight_category, median_trip, mom_pct
               FROM mart.route_card
               WHERE mom_pct IS NOT NULL
               ORDER BY trips_count DESC LIMIT 1"""
        )
    ).one()
    month, lgc, ugc, bg, wc, median, mom = cell
    prev_median = conn.execute(
        text(
            """
            WITH fct AS (
              SELECT pd.price_date AS d, p.price_rub, p.loading_city_gcid,
                     p.unloading_city_gcid, p.weight_category, g.body_group
              FROM core.prices_clean p
              JOIN public.price_dates pd ON pd.price_id = p.price_id
              JOIN core.price_body_groups g ON g.price_id = p.price_id
              WHERE p.is_fact AND NOT p.complex AND p.price_rub IS NOT NULL
                AND NOT p.outlier_mark AND pd.price_date <= :as_of
            )
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY price_rub)
            FROM fct
            WHERE date_trunc('month', d)::date = :prev
              AND loading_city_gcid = :lgc AND unloading_city_gcid = :ugc
              AND body_group = :bg AND weight_category = :wc
            """
        ),
        {"as_of": as_of,
         "prev": (month - timedelta(days=1)).replace(day=1),
         "lgc": lgc, "ugc": ugc, "bg": bg, "wc": wc},
    ).scalar()
    expected_mom = 100.0 * (float(median) / prev_median - 1)
    assert abs(float(mom) - expected_mom) < max(1e-6, abs(expected_mom) * 1e-9)

    # --- gap-month: изолированная пара городов, один месяц в истории ---
    lgc_s, ugc_s = 999001, 999002
    p_old, p_new1, p_new2 = 987650011, 987650012, 987650013
    conn.execute(text("DELETE FROM public.cities WHERE gc_id IN (:a, :b)"), {"a": lgc_s, "b": ugc_s})
    conn.execute(text("DELETE FROM public.prices WHERE id IN (:a, :b, :c)"),
                 {"a": p_old, "b": p_new1, "c": p_new2})
    conn.execute(
        text(
            """INSERT INTO public.cities (full_name_local, full_name_gc, gc_id, name)
               VALUES ('t,t', 't', :gc, 'Synthetic A'), ('u,u', 'u', :gc2, 'Synthetic B')""",
        ),
        {"gc": lgc_s, "gc2": ugc_s},
    )
    conn.execute(
        text(
            """INSERT INTO public.prices (id, loading_date, loading_city_gcid, unloading_city_gcid,
                    distance, total_weight, total_volume, body_type, price, currency_code,
                    complex, price_type, is_fact)
               VALUES
                    (:p_old, '2025-09-10', :lgc, :ugc, 1000, 15000, 60, NULL, 40000, '643', false, 2, true),
                    (:p1,    '2026-09-10', :lgc, :ugc, 1000, 15000, 60, NULL, 50000, '643', false, 2, true),
                    (:p2,    '2026-09-12', :lgc, :ugc, 1000, 15000, 60, NULL, 60000, '643', false, 2, true)
            """
        ),
        {"p_old": p_old, "p1": p_new1, "p2": p_new2, "lgc": lgc_s, "ugc": ugc_s},
    )
    conn.execute(
        text(
            """INSERT INTO public.price_dates (price_id, price_date) VALUES
               (:p_old, '2025-09-10'), (:p1, '2026-09-10'), (:p2, '2026-09-12')"""
        ),
        {"p_old": p_old, "p1": p_new1, "p2": p_new2},
    )
    conn.commit()
    try:
        run_etl(conn, date(2025, 9, 1), date(2025, 9, 30))
        run_etl(conn, date(2026, 9, 1), date(2026, 9, 30))
        build_route_card(conn, as_of)
        row = conn.execute(
            text(
                """SELECT trips_count, mom_pct, yoy_pct, reliability_level
                   FROM mart.route_card
                   WHERE loading_gc_id = :lgc AND unloading_gc_id = :ugc
                     AND month_date = '2026-09-01' AND body_group = 'Не указан'"""
            ),
            {"lgc": lgc_s, "ugc": ugc_s},
        ).one()
        trips, mom_s, yoy_s, level = row
        assert trips == 2
        assert mom_s is None  # нет ячейки 2026-08 -> NULL, а не «последний доступный»
        assert yoy_s is not None and abs(float(yoy_s) - 37.5) < 1e-9  # 100*(55000/40000-1)
        assert level == "LOW_DATA"
    finally:
        conn.execute(text("DELETE FROM public.prices WHERE id IN (:a, :b, :c)"),
                     {"a": p_old, "b": p_new1, "c": p_new2})
        conn.execute(text("DELETE FROM public.cities WHERE gc_id IN (:a, :b)"),
                     {"a": lgc_s, "b": ugc_s})
        conn.commit()
        run_etl(conn, date(2025, 9, 1), date(2025, 9, 30))
        run_etl(conn, date(2026, 9, 1), date(2026, 9, 30))
        build_route_card(conn, as_of)
