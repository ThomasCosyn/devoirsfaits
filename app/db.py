from __future__ import annotations

import threading
from contextlib import contextmanager

import psycopg
import psycopg_pool

from app.config import settings

_pool: psycopg_pool.ConnectionPool | None = None
_lock = threading.Lock()

_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS devoirsfaits;

CREATE TABLE IF NOT EXISTS devoirsfaits.classes (
    id SERIAL PRIMARY KEY,
    nom TEXT NOT NULL UNIQUE,
    annee_scolaire TEXT NOT NULL,
    programme TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS devoirsfaits.eleves (
    id SERIAL PRIMARY KEY,
    classe_id INTEGER NOT NULL REFERENCES devoirsfaits.classes(id),
    login TEXT NOT NULL UNIQUE,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    actif BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devoirsfaits.exercices (
    id SERIAL PRIMARY KEY,
    classe_id INTEGER NOT NULL REFERENCES devoirsfaits.classes(id),
    slug TEXT NOT NULL UNIQUE,
    titre TEXT NOT NULL,
    enonce TEXT NOT NULL,
    correction TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devoirsfaits.conversations (
    id SERIAL PRIMARY KEY,
    eleve_id INTEGER NOT NULL REFERENCES devoirsfaits.eleves(id),
    exercice_id INTEGER NOT NULL REFERENCES devoirsfaits.exercices(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (eleve_id, exercice_id)
);

CREATE TABLE IF NOT EXISTS devoirsfaits.messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES devoirsfaits.conversations(id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    image BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON devoirsfaits.messages (conversation_id);
"""


def get_pool() -> psycopg_pool.ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = psycopg_pool.ConnectionPool(
                    settings.DATABASE_URL,
                    min_size=1,
                    max_size=10,
                    open=True,
                    kwargs={"row_factory": psycopg.rows.dict_row},
                )
    return _pool


def init_db() -> None:
    with get_pool().connection() as conn:
        conn.execute(_SCHEMA)


@contextmanager
def get_db():
    with get_pool().connection() as conn:
        yield conn


def query_db(sql: str, params: tuple = ()) -> list[dict]:
    with get_db() as db:
        return db.execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query_db(sql, params)
    return rows[0] if rows else None
