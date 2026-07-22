import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras


@contextmanager
def get_connection():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
    finally:
        conn.close()


def get_inventory_by_item_name(item_name: str) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, item_name, quantity_available, restock_eta
                FROM core_inventoryitem
                WHERE LOWER(item_name) = LOWER(%s)
                """,
                (item_name,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
