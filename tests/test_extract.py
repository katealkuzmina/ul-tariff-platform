from datetime import date

from sqlalchemy import text


def _count(conn, sql, s, e):
    return conn.execute(text(sql), {"s": s, "e": e}).scalar()


def test_load_raw_window_twice_same_counts(conn):
    from etl.extract import load_raw_window

    s, e = date(2026, 8, 1), date(2026, 8, 31)
    load_raw_window(conn, s, e)
    n1 = _count(conn, "SELECT count(*) FROM raw.prices WHERE loading_date BETWEEN :s AND :e", s, e)
    load_raw_window(conn, s, e)
    n2 = _count(conn, "SELECT count(*) FROM raw.prices WHERE loading_date BETWEEN :s AND :e", s, e)
    assert n1 == n2 > 0
    src = _count(conn, "SELECT count(*) FROM public.prices WHERE loading_date BETWEEN :s AND :e", s, e)
    assert n1 == src


def test_load_raw_window_price_dates_in_sync(conn):
    from etl.extract import load_raw_window

    s, e = date(2026, 8, 1), date(2026, 8, 31)
    load_raw_window(conn, s, e)
    raw_pd = conn.execute(
        text(
            "SELECT count(*) FROM raw.price_dates pd "
            "JOIN raw.prices p ON p.id = pd.price_id "
            "WHERE p.loading_date BETWEEN :s AND :e"
        ),
        {"s": s, "e": e},
    ).scalar()
    src_pd = conn.execute(
        text(
            "SELECT count(*) FROM public.price_dates pd "
            "JOIN public.prices p ON p.id = pd.price_id "
            "WHERE p.loading_date BETWEEN :s AND :e"
        ),
        {"s": s, "e": e},
    ).scalar()
    assert raw_pd == src_pd > 0


def test_load_raw_window_report_read_rows(conn):
    from etl.extract import load_raw_window

    s, e = date(2026, 7, 15), date(2026, 7, 20)
    report = load_raw_window(conn, s, e)
    expected = _count(
        conn, "SELECT count(*) FROM public.prices WHERE loading_date BETWEEN :s AND :e", s, e
    )
    assert report.read_rows == expected > 0
