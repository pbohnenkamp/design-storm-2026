#!/usr/bin/env python3
"""Apply schema.sql to the database named by DATABASE_URL.

    python3 -m venv .venv && .venv/bin/pip install -r db/requirements.txt
    .venv/bin/python db/apply_schema.py

DATABASE_URL comes from the environment, or else from .env at the repo root,
e.g. DATABASE_URL=postgresql://user:password@localhost:5432/denver_water
schema.sql is idempotent, so rerunning this is safe.
"""

import os
import sys

import psycopg

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCHEMA = os.path.join(HERE, "schema.sql")


def database_url():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_path = os.path.join(REPO, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep and key.strip() == "DATABASE_URL":
                    return value.strip().strip("'\"")
    sys.exit("DATABASE_URL is not set. Export it or add it to .env at the repo root.")


def main():
    with open(SCHEMA) as f:
        sql = f.read()
    # schema.sql manages its own transaction (BEGIN ... COMMIT).
    with psycopg.connect(database_url(), autocommit=True) as conn:
        conn.execute(sql)
        db = conn.info.dbname
    print(f"Applied {os.path.relpath(SCHEMA, REPO)} to {db}.")


if __name__ == "__main__":
    main()
