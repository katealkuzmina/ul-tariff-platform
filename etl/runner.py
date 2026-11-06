"""Оркестратор end-to-end пайплайна: migrations -> ETL -> mart -> ML -> scoring.

Использование:
    python -m etl.runner all                     # полный прогон (по умолчанию)
    python -m etl.runner etl --start D --end D   # бэкфилл окна
    python -m etl.runner mart | ml | migrate
"""

import argparse
import logging
from datetime import date

from sqlalchemy import text

from etl.config import Settings, get_settings
from etl.db import connect
from etl.mart import build_route_card
from etl.migrate import run_migrations
from etl.pipeline import run_etl
from ml.predict import run_scoring
from ml.train import CATBOOST_MODEL_NAME, run_training

log = logging.getLogger("etl.runner")


def cmd_migrate(conn, settings: Settings) -> None:
    applied = run_migrations(conn)
    log.info("migrations applied: %s", applied or "(already up to date)")


def cmd_etl(conn, settings: Settings, start: date | None, end: date | None) -> None:
    if start is None or end is None:
        lo, hi = conn.execute(
            text("SELECT min(loading_date), max(loading_date) FROM public.prices")
        ).one()
        start = start or lo
        end = end or hi
    report = run_etl(conn, start, end)
    log.info(
        "ETL window %s..%s: read=%d loaded=%d quarantined=%d by_reason=%s",
        start, end, report.read_rows, report.loaded, report.quarantined, report.by_reason,
    )


def cmd_mart(conn, settings: Settings) -> None:
    report = build_route_card(conn, settings.as_of)
    log.info("mart.route_card: rows=%d max_month=%s", report.rows, report.max_month)
    import os

    if os.environ.get("REPLICATE_TO_CH") == "1":
        from etl.mart_ch import replicate_route_card

        replicate_route_card(conn)


def cmd_ml(conn, settings: Settings) -> None:
    results = run_training(conn, settings)
    n = run_scoring(conn, CATBOOST_MODEL_NAME, settings.as_of)
    log.info("scored rows: %d", n)
    print("\n=== Model metrics (test window) ===")
    for r in results:
        print(
            f"{r.model_name:12s} R2={r.metrics['r2']:.4f}  MAPE={r.metrics['mape_pct']:.2f}%  "
            f"RMSE={r.metrics['rmse_rub']:.0f} RUB  MAE={r.metrics['mae_rub']:.0f} RUB  "
            f"(train={r.train_rows}, test={r.test_rows})"
        )


def cmd_all(conn, settings: Settings) -> None:
    cmd_migrate(conn, settings)
    cmd_etl(conn, settings, None, None)
    cmd_mart(conn, settings)
    cmd_ml(conn, settings)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    parser = argparse.ArgumentParser(description="Smart Logistics DWH/ML pipeline runner")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("all", help="full pipeline (default)")
    p_etl = sub.add_parser("etl", help="ETL for a loading_date window")
    p_etl.add_argument("--start", type=date.fromisoformat, default=None)
    p_etl.add_argument("--end", type=date.fromisoformat, default=None)
    sub.add_parser("migrate", help="apply DWH migrations only")
    sub.add_parser("mart", help="rebuild mart.route_card only")
    sub.add_parser("ml", help="train models and run batch scoring only")
    args = parser.parse_args()

    settings = get_settings()
    command = args.command or "all"
    with connect(settings) as conn:
        if command == "etl":
            cmd_etl(conn, settings, args.start, args.end)
        elif command == "migrate":
            cmd_migrate(conn, settings)
        elif command == "mart":
            cmd_mart(conn, settings)
        elif command == "ml":
            cmd_ml(conn, settings)
        else:
            cmd_all(conn, settings)


if __name__ == "__main__":
    main()
