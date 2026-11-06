"""DAG тарифного пайплайна (бонус-оркестрация Apache Airflow).

Запуск вручную из UI (schedule=None) или:
    docker compose exec airflow-webserver airflow dags trigger tariff_pipeline

Повторный запуск за тот же период идемпотентен (те же гарантии, что у
сервиса app: DELETE+INSERT по окнам и model_name).

Подключение к БД — через переменные окружения (AIRFLOW_CONN_POSTGRES_DEFAULT
синхронизирован с DATABASE_URL, которое читает etl.config.Settings).
"""

import os
from datetime import date, datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

DEFAULT_ARGS = {
    "owner": "data-engineering",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _settings():
    from etl.config import get_settings

    return get_settings()


def _connect():
    from etl.db import connect

    return connect(_settings())


def task_migrate() -> None:
    from etl.migrate import run_migrations

    with _connect() as conn:
        applied = run_migrations(conn)
    print("migrations applied:", applied or "(up to date)")


def task_etl(**context) -> None:
    from sqlalchemy import text

    from etl.pipeline import run_etl

    params = context["params"]
    with _connect() as conn:
        start = date.fromisoformat(params["start_date"]) if params.get("start_date") else None
        end = date.fromisoformat(params["end_date"]) if params.get("end_date") else None
        if start is None or end is None:
            lo, hi = conn.execute(
                text("SELECT min(loading_date), max(loading_date) FROM public.prices")
            ).one()
            start = start or lo
            end = end or hi
        report = run_etl(conn, start, end)
    print(f"ETL {start}..{end}: read={report.read_rows} loaded={report.loaded} "
          f"quarantined={report.quarantined} by_reason={report.by_reason}")


def task_mart() -> None:
    from etl.mart import build_route_card

    with _connect() as conn:
        report = build_route_card(conn, _settings().as_of)
    print(f"mart.route_card: rows={report.rows} max_month={report.max_month}")


def task_train() -> None:
    from ml.train import run_training

    with _connect() as conn:
        results = run_training(conn, _settings())
    for r in results:
        print(f"{r.model_name}: {r.metrics}")


def task_score() -> None:
    from ml.predict import run_scoring
    from ml.train import CATBOOST_MODEL_NAME

    with _connect() as conn:
        n = run_scoring(conn, CATBOOST_MODEL_NAME, _settings().as_of)
    print(f"scored rows: {n}")


with DAG(
    dag_id="tariff_pipeline",
    description="DWH ETL -> mart -> ML training -> batch scoring (idempotent)",
    schedule=None,          # только ручной запуск/бэкфилл; автозапуск не включён
    catchup=False,
    start_date=datetime(2026, 1, 1),
    default_args=DEFAULT_ARGS,
    params={
        "start_date": "",   # пусто = полный диапазон public.prices
        "end_date": "",
    },
    tags=["tariff", "dwh", "ml"],
) as dag:
    migrate = PythonOperator(task_id="migrate", python_callable=task_migrate)
    etl = PythonOperator(task_id="etl", python_callable=task_etl)
    mart = PythonOperator(task_id="mart", python_callable=task_mart)
    train = PythonOperator(task_id="train", python_callable=task_train)
    score = PythonOperator(task_id="score", python_callable=task_score)

    migrate >> etl >> mart >> train >> score
