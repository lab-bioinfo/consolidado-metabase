"""Conexión de lectura; las credenciales se suministran por entorno."""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor


@contextmanager
def connection():
    password = os.environ.get("STREAMLIT_DB_PASSWORD")
    if not password:
        raise RuntimeError("Falta STREAMLIT_DB_PASSWORD en el entorno.")
    with psycopg2.connect(
        host=os.environ.get("STREAMLIT_DB_HOST", "localhost"),
        port=os.environ.get("STREAMLIT_DB_PORT", "5432"),
        dbname=os.environ.get("STREAMLIT_DB_NAME", "antimicrobianos"),
        user=os.environ.get("STREAMLIT_DB_USER", "metabase"),
        password=password,
        options="-c default_transaction_read_only=on",
        connect_timeout=5,
    ) as conn:
        yield conn


def fetch(sql: str, params: tuple = ()) -> list[dict]:
    with connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
