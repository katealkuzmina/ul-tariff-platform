from datetime import date

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
