"""Conexion a Postgres."""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

DEFAULT_URL = "postgresql://golf:golf@localhost:5433/golf"


def database_url() -> str:
    return os.getenv("DATABASE_URL") or DEFAULT_URL


def connect(*, autocommit: bool = False) -> psycopg.Connection:
    """Conexion con filas como dict (mas comodo para serializar a JSON)."""
    return psycopg.connect(database_url(), row_factory=dict_row, autocommit=autocommit)
