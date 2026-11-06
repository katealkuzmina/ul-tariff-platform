from sqlalchemy import text


def test_dwh_schemas_exist(conn):
    names = {
        r[0]
        for r in conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema IN ('raw','core','mart')"
            )
        )
    }
    assert {"prices", "price_dates"} <= names  # raw
    assert {"prices_clean", "dq_quarantine_prices", "price_body_groups", "dim_cities"} <= names
    assert {"route_card", "ml_price_predictions", "model_metrics"} <= names


def test_run_migrations_is_idempotent(conn, migrated):
    from etl.migrate import run_migrations

    applied = {
        r[0] for r in conn.execute(text("SELECT migration FROM public.schema_migrations"))
    }
    assert applied == {"01_raw.sql", "02_core.sql", "03_mart.sql"}
    assert run_migrations(conn) == []
