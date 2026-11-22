FROM apache/airflow:3.1.8-python3.11

WORKDIR /opt/fdep
COPY requirements.txt requirements-dbt.txt ./
RUN python -m venv /home/airflow/fdep-venv \
    && /home/airflow/fdep-venv/bin/pip install --no-cache-dir -r requirements.txt -r requirements-dbt.txt

COPY config/ config/
COPY dbt/ dbt/
COPY orchestration/ orchestration/
COPY scripts/ scripts/
COPY warehouse/ warehouse/
