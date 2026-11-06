FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/airflow

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/opt/airflow

# Airflow ставим отдельным окружением поверх python 3.12
# Airflow 3.x + SQLAlchemy 2 (код etl/ml использует SA 2 API: Connection.commit() и т.д.)
RUN uv venv /opt/airflow/venv \
    && uv pip install --python /opt/airflow/venv/bin/python \
        "apache-airflow[postgres]==3.4.0" \
        "apache-airflow-providers-postgres" \
        "SQLAlchemy>=2.0,<2.1" \
        "psycopg[binary]" "pandas" "numpy" "scikit-learn" "catboost" "python-dateutil"

COPY dags/ /opt/airflow/dags/
COPY etl/ /opt/airflow/etl/
COPY ml/ /opt/airflow/ml/
COPY sql/ /opt/airflow/sql/
COPY pyproject.toml /opt/airflow/

ENV PATH="/opt/airflow/venv/bin:$PATH" \
    AIRFLOW_HOME=/opt/airflow \
    AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags \
    AIRFLOW__CORE__LOAD_EXAMPLES=False \
    AIRFLOW__CORE__EXECUTOR=LocalExecutor

CMD ["airflow", "api-server", "--host", "0.0.0.0", "--port", "8080"]
