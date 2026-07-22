"""
Direct Postgres queries against Django-managed tables.

Table names follow Django convention: core_order, core_inventoryitem, core_refundpolicy
"""

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is required")
    return url


@contextmanager
def get_connection():
    conn = psycopg2.connect(get_database_url())
    try:
        yield conn
    finally:
        conn.close()


def get_order_by_id(order_id: str | int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, customer_name, item_name, item_category, status,
                       order_date, tracking_number
                FROM core_order
                WHERE id = %s
                """,
                (int(order_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None
