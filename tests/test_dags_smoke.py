"""Smoke-тест DAG-файла без установленного Airflow: синтаксис, структура,
и что все вызываемые пайплайн-функции существуют и импортируются."""

import ast
from pathlib import Path

DAG_PATH = Path(__file__).resolve().parent.parent / "dags" / "tariff_pipeline_dag.py"


def _task_functions(tree):
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("task_")
    }


def test_dag_file_parses_and_declares_all_stages():
    tree = ast.parse(DAG_PATH.read_text(encoding="utf-8"))
    tasks = _task_functions(tree)
    assert tasks == {"task_migrate", "task_etl", "task_mart", "task_train", "task_score"}


def test_dag_references_existing_pipeline_functions():
    tree = ast.parse(DAG_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported.add((node.module, alias.name))
    needed = {
        ("etl.migrate", "run_migrations"),
        ("etl.pipeline", "run_etl"),
        ("etl.mart", "build_route_card"),
        ("ml.train", "run_training"),
        ("ml.predict", "run_scoring"),
    }
    assert needed <= imported
    # и символы реально импортируются в окружении приложения
    from etl.mart import build_route_card  # noqa: F401
    from etl.migrate import run_migrations  # noqa: F401
    from etl.pipeline import run_etl  # noqa: F401
    from ml.predict import run_scoring  # noqa: F401
    from ml.train import run_training  # noqa: F401


def test_dag_is_manual_trigger_only():
    source = DAG_PATH.read_text(encoding="utf-8")
    assert "schedule=None" in source
    assert "catchup=False" in source
    assert 'dag_id="tariff_pipeline"' in source
