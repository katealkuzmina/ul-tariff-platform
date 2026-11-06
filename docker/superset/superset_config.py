"""Конфигурация Superset для docker-образа (загружается из PYTHONPATH).

Официальный образ apache/superset подхватывает модуль superset_config
из /app/pythonpath — здесь задаём мета-БД в PostgreSQL и SECRET_KEY из env.
"""

import os

SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///" + os.path.join(os.path.expanduser("~"), ".superset/superset.db"),
)
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "ul-tariff-dev-secret-key")

ROW_LIMIT = 5000
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False
