from datetime import date

from sqlalchemy import text


def count_clean(conn, s, e):
    return conn.execute(
        text("SELECT count(*) FROM core.prices_clean WHERE loading_date BETWEEN :s AND :e"),
        {"s": s, "e": e},
    ).scalar()


def test_core_clean_and_quarantine(conn):
    from etl.pipeline import run_etl

    rep = run_etl(conn, date(2026, 7, 1), date(2026, 10, 26))
    assert rep.quarantined > 0
    assert rep.by_reason["FX_RATE_MISSING"] > 0
    bad = conn.execute(
        text(
            "SELECT count(*) FROM core.prices_clean "
            "WHERE price_rub <= 0 OR distance <= 0 OR total_weight < 0 OR total_volume < 0"
        )
    ).scalar()
    assert bad == 0
    rub = conn.execute(
        text(
            "SELECT count(*) FROM core.prices_clean "
            "WHERE currency_code='643' AND price_rub <> round(price::numeric,2)"
        )
    ).scalar()
    assert rub == 0
    fx = conn.execute(
        text(
            "SELECT count(*) FROM core.prices_clean "
            "WHERE currency_code <> '643' AND price_rub IS NULL"
        )
    ).scalar()
    assert fx == 0
    unknown = conn.execute(
        text(
            "SELECT count(*) FROM core.prices_clean p "
            "WHERE NOT EXISTS (SELECT 1 FROM core.dim_cities c WHERE c.gc_id = p.loading_city_gcid)"
        )
    ).scalar()
    assert unknown == 0
    # карантин содержит причины из канонического множества
    bad_reasons = conn.execute(
        text("SELECT DISTINCT reason_code FROM core.dq_quarantine_prices")
    ).scalars().all()
    assert set(bad_reasons) <= {
        "INVALID_PRICE",
        "INVALID_PRICE_RANGE",
        "INVALID_DISTANCE",
        "INVALID_WEIGHT",
        "INVALID_VOLUME",
        "CITY_NOT_FOUND",
        "FX_RATE_MISSING",
    }
    # валютные строки в витрине пересчитаны по курсу: price_rub/price == курс ЦБ
    mismatch = conn.execute(
        text(
            "SELECT count(*) FROM core.prices_clean pc "
            "JOIN raw.prices pc_nearest ON pc_nearest.id = pc.price_id "
            "JOIN public.exchange_rates er ON er.num_code = pc.currency_code "
            "AND er.setting_date = pc_nearest.nearest_rate_date "
            "WHERE pc.currency_code <> '643' "
            "AND abs(pc.price_rub - round((pc.price * er.value)::numeric, 2)) > 0.01"
        )
    ).scalar()
    assert mismatch == 0


def test_etl_rerun_idempotent(conn):
    from etl.pipeline import run_etl

    run_etl(conn, date(2026, 9, 1), date(2026, 9, 30))
    n1 = count_clean(conn, date(2026, 9, 1), date(2026, 9, 30))
    run_etl(conn, date(2026, 9, 1), date(2026, 9, 30))
    n2 = count_clean(conn, date(2026, 9, 1), date(2026, 9, 30))
    assert n1 == n2 > 0
    q1 = conn.execute(
        text(
            "SELECT count(*) FROM core.dq_quarantine_prices "
            "WHERE loading_date BETWEEN '2026-09-01' AND '2026-09-30'"
        )
    ).scalar()
    assert q1 > 0


def test_dim_cities_dedup_and_body_groups(conn):
    from etl.pipeline import run_etl

    run_etl(conn, date(2026, 8, 1), date(2026, 8, 31))
    n_cities_src = conn.execute(
        text("SELECT count(DISTINCT gc_id) FROM public.cities")
    ).scalar()
    n_cities_dim = conn.execute(text("SELECT count(*) FROM core.dim_cities")).scalar()
    assert n_cities_dim == n_cities_src == 40
    dup = conn.execute(
        text(
            "SELECT count(*) FROM (SELECT price_id, body_group FROM core.price_body_groups "
            "GROUP BY 1, 2 HAVING count(*) > 1) t"
        )
    ).scalar()
    assert dup == 0
    allowed = {"Тент", "Рефрижератор", "Изотерм", "Борт", "Прочие", "Не указан"}
    groups = set(conn.execute(text("SELECT DISTINCT body_group FROM core.price_body_groups")).scalars())
    assert groups <= allowed and "Тент" in groups
    # fallback: у сделок без price_body_types группа из prices.body_type
    null_link = conn.execute(
        text(
            "SELECT count(*) FROM public.prices p WHERE p.body_type IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM public.price_body_types pbt WHERE pbt.price_id = p.id)"
        )
    ).scalar()
    assert null_link > 0
