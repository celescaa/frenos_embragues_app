"""Fixtures compartidas por toda la suite.

La base de pruebas es el Postgres local que levanta `npx supabase start`
(ver README). Cada test corre dentro de una transacción que se revierte al
terminar, así que los tests no se ensucian entre sí.
"""
import os
import pytest
import psycopg
from psycopg.rows import dict_row

PG_URL_TEST = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
)


@pytest.fixture(scope="session")
def pg_url():
    return PG_URL_TEST


@pytest.fixture
def db_conn(pg_url):
    """Conexión con rollback automático: nada de lo que escribe un test queda."""
    conn = psycopg.connect(pg_url, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
